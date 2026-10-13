"""Validate a replay's structure and export a self-contained HTML player.

For full rules/ASCII verification, run `fff-runner verify MATCH_DIR` first.
"""
import argparse
import json
from pathlib import Path
from schema import Validator, integer, obj, array, text, U64

MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_FRAMES = 25000


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
    validator=Validator(game_map)
    players=validator.players
    if last>validator.max_turns:
        raise ValueError("manifest.json.last_complete_turn: exceeds map limit")
    teams=array(manifest.get("teams"),"manifest.json.teams")
    if len(teams)!=players:
        raise ValueError("manifest.json.teams: wrong count")
    for i,team in enumerate(teams):
        label=f"manifest.json.teams[{i}]"
        team=obj(team,label)
        integer(team.get("team_id"),i,i,label+".team_id")
        text(team.get("name"),label+".name")
        if team.get("ai_seed") is not None:
            team["ai_seed"]=str(integer(team["ai_seed"],0,U64,label+".ai_seed"))
    text(manifest.get("match_id"),"manifest.json.match_id")
    integer(manifest.get("seed"),0,U64,"manifest.json.seed")
    initial_record = read("initial.json")
    if initial_record.get("format_version") != 1:
        raise ValueError("unsupported initial format version")
    initial = validator.state(initial_record.get("state"), 0, "initial.json.state")
    records = []
    for turn in range(1, last + 1):
        record = read(f"frames/{turn:06d}.json")
        if record.get("format_version") != 1 or record.get("call_order") != list(range(players)):
            raise ValueError(f"invalid frame metadata at {turn}")
        frame = obj(record.get("frame"),f"frames/{turn:06d}.json.frame")
        if frame.get("turn") != turn:
            raise ValueError(f"invalid frame turn at {turn}")
        validator.state(frame.get("start"), turn, f"frames/{turn:06d}.json.frame.start")
        validator.state(frame.get("end"), turn, f"frames/{turn:06d}.json.frame.end")
        if not isinstance(frame.get("events"), list) or len(frame["events"]) > 10000:
            raise ValueError(f"invalid frame events at {turn}")
        for i,event in enumerate(frame["events"]):
            validator.event(event,f"frames/{turn:06d}.json.frame.events[{i}]")
        calls = array(record.get("calls"),f"frames/{turn:06d}.json.calls")
        if len(calls)!=players:
            raise ValueError(f"frames/{turn:06d}.json.calls: wrong count")
        for i,call in enumerate(calls):
            label=f"frames/{turn:06d}.json.calls[{i}]"
            call=obj(call,label)
            integer(call.get("team_id"),i,i,label+".team_id")
            integer(call.get("turn"),turn,turn,label+".turn")
            if call.get("status") not in ("ok","timeout","crash","load_error","protocol_error","ai_error"):
                raise ValueError(label+".status: unknown status")
            integer(call.get("elapsed_us"),0,U64,label+".elapsed_us")
            integer(call.get("init_elapsed_us"),0,U64,label+".init_elapsed_us")
        records.append(record)
    summary = read("summary.json") if manifest["status"] == "complete" else None
    if summary is not None and (summary.get("complete") is not True or summary.get("turns") != last or summary.get("scores") != (records[-1]["frame"]["end"]["scores"] if records else initial["scores"])):
        raise ValueError("summary.json: differs from final state")
    manifest["seed"] = str(manifest.get("seed", 0))
    return {"bundle_format": "fff-replay", "bundle_version": 1,
            "manifest": manifest, "map": game_map, "initial": initial, "records": records, "summary": summary}


def write_html(payload, output):
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for character, escape in (("<", r"\u003c"), (">", r"\u003e"), ("&", r"\u0026"), ("\u2028", r"\u2028"), ("\u2029", r"\u2029")):
        encoded = encoded.replace(character, escape)
    assets = Path(__file__).parent
    template = (assets / "index.html").read_text(encoding="utf-8")
    marker = '<script id="replay-data" type="application/json">null</script>'
    if template.count(marker) != 1:
        raise ValueError("invalid player template")
    template = template.replace('<link rel="stylesheet" href="player.css">',
                                '<style>' + (assets / "player.css").read_text(encoding="utf-8") + '</style>')
    template = template.replace('<script src="player.js"></script>',
                                '<script>' + (assets / "player.js").read_text(encoding="utf-8") + '</script>')
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.replace(marker, f'<script id="replay-data" type="application/json">{encoded}</script>'), encoding="utf-8")
    return target


def export(directory, output):
    return write_html(load_replay(directory), output)


def write_data(payload, output):
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--format", choices=("html", "json", "both"), default="both",
                        help="default: both HTML player and single JSON data file")
    args = parser.parse_args()
    try:
        html = args.out or args.directory / "replay.html"
        data = (args.out if args.format == "json" else args.out.with_suffix(".json") if args.out else None)
        data = data or args.directory / "replay.json"
        if args.format == "both" and html.resolve() == data.resolve():
            raise ValueError("HTML and JSON outputs must differ; use --out FILE.html or --format json")
        payload = load_replay(args.directory)
        targets = []
        if args.format in ("html", "both"):
            targets.append(write_html(payload, html))
        if args.format in ("json", "both"):
            targets.append(write_data(payload, data))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"replay export failed: {error}\n")
    for target in targets:
        print(target)

if __name__ == "__main__":
    main()
