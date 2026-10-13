"""Run real 2/8-team release matches, verify records, and export offline players."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("runs/smoke-v1"))
    parser.add_argument("--bin-dir", type=Path, default=Path("target/release"))
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"output already exists: {args.out}")
    args.out.mkdir(parents=True)
    runner = args.bin_dir / "fff-runner"
    for players, names in ((2, ("baseline", "greedy")), (8, ("baseline",) * 8)):
        directory = args.out / f"{players}p"
        command = [str(runner), "--map", f"maps/arena_{players}p.ron", "--seed", "41", "--out", str(directory)]
        for name in names:
            command.extend(("--ai", str(args.bin_dir / f"libfff_bot_{name}.so")))
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        summary = json.loads(result.stdout)
        assert not any(summary["ai_failures"]), summary
        assert not any(summary["illegal_actions"]), summary
        subprocess.run([str(runner), "verify", str(directory)], check=True)
        subprocess.run([sys.executable, "viewer/export.py", str(directory)], check=True)
        events = Counter()
        for frame in (directory / "frames").glob("*.json"):
            record = json.loads(frame.read_text())
            events.update(event["type"] for event in record["frame"]["events"])
        print(json.dumps({"players": players, "summary": summary, "events": dict(events), "replay": str(directory / "replay.html")}, ensure_ascii=False), flush=True)
    print("PASS: 2-team and 8-team release matches, replay verification and HTML export", flush=True)

if __name__ == "__main__":
    main()
