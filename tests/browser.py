"""Exercise the exported player using a real local Chromium browser."""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.goto(args.html.resolve().as_uri())
        expect(page.locator("#turnLabel")).to_contain_text("初始局面")
        players = page.evaluate("data.map.players")
        expect(page.locator(".unit")).to_have_count(players * 3)
        page.locator("#next").click()
        expect(page.locator("#jump")).to_have_value("1")
        page.locator("#prev").click()
        expect(page.locator("#jump")).to_have_value("0")
        page.locator("#jump").fill("5")
        page.locator("#jump").press("Tab")
        expect(page.locator("#jump")).to_have_value("5")
        page.locator("#phase").select_option("start")
        expect(page.locator("#frameNote")).to_contain_text("AI 决策前")
        page.locator("#phase").select_option("end")
        page.locator("#speed").select_option("8")
        page.locator("#play").click()
        page.wait_for_function("Number(document.getElementById('jump').value)>5")
        page.locator("#play").click()
        expect(page.locator("#play")).to_have_text("播放")
        if args.screenshot:
            page.screenshot(path=str(args.screenshot), full_page=True)
        # Manual numeric input must resolve to an integer frame, not crash on 1.5.
        page.locator("#jump").fill("1.5")
        page.locator("#jump").press("Tab")
        expect(page.locator("#jump")).to_have_value("1")
        assert not errors, errors
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#next").click()
        expect(page.locator("#jump")).to_have_value("2")
        assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"), "mobile page overflows"
        browser.close()
        print("PASS: offline player next/previous/jump/START-END/playback/speed/fractional input/mobile layout")

if __name__ == "__main__":
    main()
