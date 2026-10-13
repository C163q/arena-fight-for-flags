"""Validate a replay's structure and export a self-contained HTML player.

For full rules/ASCII verification, run `fff-runner verify MATCH_DIR` first.
"""
import argparse
import json
from pathlib import Path

MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_FRAMES = 25000


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"invalid {label}: expected integer {low}..{high}")
    return value


def load_replay(directory):
    root = Path(directory).resolve(strict=True)
    total = 0

    def read(relative):
        nonlocal total
        path = root / relative
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise ValueError(f"path escapes replay directory: {relative}")
            size = resolved.stat().st_size
            total += size
            if size > MAX_FILE or total > MAX_TOTAL:
                raise ValueError(f"replay size limit exceeded: {relative}")
            with resolved.open(encoding="utf-8") as stream:
                result = json.load(stream)
            if not isinstance(result, dict):
                raise ValueError("expected JSON object")
            return result
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"{relative}: {error}") from error

    manifest = read("manifest.json")
    if manifest.get("format_version") != 1:
        raise ValueError("unsupported replay format version")
    if manifest.get("status") not in ("complete", "in_progress"):
        raise ValueError("invalid manifest status")
    last = integer(manifest.get("last_complete_turn"), 0, MAX_FRAMES, "last_complete_turn")
    game_map = read("map.json")
    if game_map.get("format_version") != 1:
        raise ValueError("unsupported map format version")
    width = integer(game_map.get("width"), 9, 128, "map width")
    height = integer(game_map.get("height"), 9, 128, "map height")
    players = integer(game_map.get("players"), 2, 8, "team count")
    terrain = game_map.get("terrain")
    if not isinstance(terrain, list) or len(terrain) != height or any(not isinstance(row, str) or len(row) != width or set(row) - {"#", "."} for row in terrain):
        raise ValueError("invalid terrain")
    if any(c != "#" for c in terrain[0] + terrain[-1]) or any(row[0] != "#" or row[-1] != "#" for row in terrain):
        raise ValueError("unsealed map border")
    if len(manifest.get("teams", [])) != players or any(team.get("team_id") != i or not isinstance(team.get("name"), str) for i, team in enumerate(manifest["teams"])):
        raise ValueError("invalid teams")
    homes = game_map.get("spawn_regions", [])
    sites = game_map.get("flag_points", [])
    if len(homes) != players or not 1 <= len(sites) <= 32:
        raise ValueError("invalid homes or flag sites")

    def position(p, label):
        if not isinstance(p, dict):
            raise ValueError(f"invalid {label} position")
        x = integer(p.get("x"), 0, width - 1, f"{label} x")
        y = integer(p.get("y"), 0, height - 1, f"{label} y")
        if terrain[y][x] != ".":
            raise ValueError(f"{label} position is blocked")
        return x, y

    def state(value, turn):
        if not isinstance(value, dict) or value.get("turn") != turn:
            raise ValueError("invalid state turn")
        scores = value.get("scores", [])
        if len(scores) != players:
            raise ValueError("invalid scores")
        for score in scores:
            integer(score, 0, 4294967295, "score")
        units = value.get("units", [])
        if len(units) != players * 3:
            raise ValueError("invalid unit count")
        occupied = set()
        for i, unit in enumerate(units):
            if unit.get("id") != {"team_id": i // 3, "unit_id": i % 3}:
                raise ValueError("invalid unit ID")
            hp = integer(unit.get("hp"), 0, 3, "unit hp")
            p = unit.get("position")
            if p is None:
                if hp != 0 or unit.get("carrying") is not None:
                    raise ValueError("invalid dead unit")
            else:
                cell = position(p, "unit")
                if hp == 0 or cell in occupied:
                    raise ValueError("invalid unit occupancy")
                occupied.add(cell)
        flags = value.get("flags", [])
        if not isinstance(flags, list) or len(flags) > len(sites):
            raise ValueError("invalid flags")
        for flag in flags:
            location = flag.get("location", {})
            if location.get("state") == "ground":
                position(location.get("position"), "flag")
            elif location.get("state") != "carried":
                raise ValueError("invalid flag location")
        # Preserve exact 64-bit metadata when JSON is parsed by JavaScript.
        value["rng_state"] = str(value.get("rng_state", 0))
        return value

    initial_record = read("initial.json")
    if initial_record.get("format_version") != 1:
        raise ValueError("unsupported initial format version")
    initial = state(initial_record.get("state"), 0)
    records = []
    for turn in range(1, last + 1):
        record = read(f"frames/{turn:06d}.json")
        if record.get("format_version") != 1 or record.get("call_order") != list(range(players)):
            raise ValueError(f"invalid frame metadata at {turn}")
        frame = record.get("frame", {})
        if frame.get("turn") != turn:
            raise ValueError(f"invalid frame turn at {turn}")
        state(frame.get("start"), turn)
        state(frame.get("end"), turn)
        if not isinstance(frame.get("events"), list) or len(frame["events"]) > 10000:
            raise ValueError(f"invalid frame events at {turn}")
        calls = record.get("calls", [])
        if len(calls) != players or any(call.get("team_id") != i or call.get("turn") != turn for i, call in enumerate(calls)):
            raise ValueError(f"invalid frame calls at {turn}")
        records.append(record)
    summary = read("summary.json") if manifest["status"] == "complete" else None
    if summary and (summary.get("turns") != last or summary.get("scores") != (records[-1]["frame"]["end"]["scores"] if records else initial["scores"])):
        raise ValueError("summary differs from final state")
    manifest["seed"] = str(manifest.get("seed", 0))
    return {"manifest": manifest, "map": game_map, "initial": initial, "records": records, "summary": summary}


def export(directory, output):
    payload = load_replay(directory)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for character, escape in (("<", r"\u003c"), (">", r"\u003e"), ("&", r"\u0026"), ("\u2028", r"\u2028"), ("\u2029", r"\u2029")):
        encoded = encoded.replace(character, escape)
    template = Path(__file__).with_name("template.html").read_text(encoding="utf-8")
    if template.count("__REPLAY_DATA__") != 1:
        raise ValueError("invalid player template")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.replace("__REPLAY_DATA__", encoded), encoding="utf-8")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        target = export(args.directory, args.out or args.directory / "replay.html")
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"replay export failed: {error}\n")
    print(target)

if __name__ == "__main__":
    main()
