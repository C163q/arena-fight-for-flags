"""Real Chromium checks for replay loading, layout, board navigation and health bars."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("data", type=Path)
    parser.add_argument("--player", type=Path, default=Path("viewer/index.html"))
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    with sync_playwright() as pw, tempfile.TemporaryDirectory(prefix="fff-viewer-browser-") as tmp:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.html.resolve().as_uri())
        assert page.evaluate("document.documentElement.scrollHeight<=innerHeight"), "8-team page is taller than viewport"
        expect(page.locator("#events")).to_be_visible()
        for width, height in ((1440, 900), (1366, 768)):
            page.set_viewport_size({"width": width, "height": height})
            board = page.locator("#boardViewport").bounding_box()
            events = page.locator("#events").bounding_box()
            assert board["height"] > 300 and board["y"] + board["height"] <= height, "board clipped"
            assert events["height"] > 200 and events["y"] + events["height"] <= height, "events clipped"
        page.set_viewport_size({"width": 1440, "height": 900})
        page.locator("#tab-units").click()
        expect(page.locator("#units .unit")).to_have_count(24)
        page.locator("#tab-events").click()
        expect(page.locator("#health-bars rect")).to_have_count(0)
        # Zoom and dragging must affect the visible world and survive a turn change.
        original = page.locator("#board").get_attribute("viewBox")
        page.locator("#zoom-in").click()
        zoomed = page.locator("#board").get_attribute("viewBox")
        assert original != zoomed, "zoom button has no effect"
        page.locator("#next").click()
        assert page.locator("#board").get_attribute("viewBox") == zoomed, "turn change resets zoom"
        box = page.locator("#board").bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 60, y + 40, steps=4)
        page.mouse.up()
        assert page.locator("#board").get_attribute("viewBox") != zoomed, "drag has no effect"
        page.locator("#fit").click()
        assert page.locator("#board").get_attribute("viewBox") == original
        page.mouse.move(x, y)
        page.mouse.wheel(0, -300)
        page.wait_for_function("document.getElementById('zoomLabel').textContent!=='100%'")
        page.locator("#fit").click()
        page.locator("#fullscreen").click()
        page.wait_for_function("Boolean(document.fullscreenElement)")
        page.evaluate("document.exitFullscreen()")
        page.wait_for_function("!document.fullscreenElement")
        if args.screenshot:
            page.screenshot(path=str(args.screenshot), full_page=True)
        page.goto(args.player.resolve().as_uri())
        expect(page.locator("#empty")).to_be_visible()
        page.locator("#file").set_input_files(str(args.data))
        expect(page.locator("#turnLabel")).to_contain_text("初始局面")
        expect(page.locator("#meta")).to_contain_text("8 队")
        # Loading corrupt data preserves the current match and shows a useful error.
        payload = json.loads(args.data.read_text())
        bad = Path(tmp) / "broken.json"
        for fields, value in ((('bundle_version',), 999), (('initial', 'sites'), None), (('map', 'width'), 999999),
                              (('records', 0, 'frame', 'events'), [None]),
                              (('records', 0, 'frame', 'events'), [{"type": "shot", "event_id": "x", "phase": "shoot", "shooter": None}])):
            broken = copy.deepcopy(payload)
            cursor = broken
            for field in fields[:-1]:
                cursor = cursor[field]
            cursor[fields[-1]] = value
            bad.write_text(json.dumps(broken))
            page.locator("#file").set_input_files(str(bad))
            expect(page.locator("#loadError")).not_to_be_empty()
            expect(page.locator("#meta")).to_contain_text("8 队")
            page.locator("#next").click()
        # Drop a new valid match while playing. Only injured living units get bars.
        fixture = copy.deepcopy(payload)
        fixture["initial"]["units"][0]["hp"] = 2
        fixture["manifest"]["match_id"] = "drop-health-check"
        fixture["manifest"]["teams"][0]["name"] = "<img src=x onerror=alert(1)>"
        page.locator("#play").click()
        page.evaluate("""payload => {
            const transfer = new DataTransfer();
            transfer.items.add(new File([JSON.stringify(payload)], 'dropped.json', {type:'application/json'}));
            document.dispatchEvent(new DragEvent('drop', {bubbles:true, dataTransfer:transfer}));
        }""", fixture)
        expect(page.locator("#jump")).to_have_value("0")
        expect(page.locator("#play")).to_have_text("播放")
        expect(page.locator("#loadError")).to_be_empty()
        expect(page.locator("#health-bars rect")).to_have_count(3)
        assert page.locator("#scores img").count() == 0, "team name interpreted as HTML"
        page.locator("#board [data-unit='A']").click()
        expect(page.locator("#selection")).to_contain_text("HP 2/3")
        # A late completion from an earlier file choice cannot replace the newer match.
        page.evaluate("""payload => {
            function drop(name, delay) {
                const file = new File(['{}'], name);
                file.text = () => new Promise(resolve => setTimeout(() => resolve(JSON.stringify(payload)), delay));
                const transfer = new DataTransfer(); transfer.items.add(file);
                document.dispatchEvent(new DragEvent('drop', {bubbles:true, dataTransfer:transfer}));
            }
            drop('older.json', 180); drop('newer.json', 0);
        }""", fixture)
        expect(page.locator("#loadedFile")).to_have_text("newer.json")
        page.wait_for_timeout(250)
        expect(page.locator("#loadedFile")).to_have_text("newer.json")
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#zoom-in").click()
        page.locator("#next").click()
        expect(page.locator("#jump")).to_have_value("1")
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), "mobile horizontal overflow"
        assert not errors, errors
        browser.close()
        print("PASS: bounded 8-team layout, zoom/pan/fit/fullscreen, load/drop/error recovery/race, health bars, mobile")


if __name__ == "__main__":
    main()
