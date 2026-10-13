"""Run seeded, slot-rotated reference-AI evaluations through the public CLI."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess


def percentile(values, percent):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, (len(ordered) - 1) * percent // 100)] if ordered else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("runs/evaluation-v1"))
    parser.add_argument("--report", type=Path, default=Path("docs/evaluation-2026-10-13.md"))
    parser.add_argument("--bin-dir", type=Path, default=Path("target/release"))
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"output already exists: {args.out}")
    args.out.mkdir(parents=True)
    runner = args.bin_dir / "fff-runner"
    scenarios = [(2, "greedy", seed, slot) for seed in range(6) for slot in range(2)]
    scenarios += [(2, "wait", seed, slot) for seed in range(2) for slot in range(2)]
    scenarios += [(players, "greedy", 17, slot) for players in range(3, 9) for slot in range(players)]
    rows = []
    cpu_lines = Path("/proc/cpuinfo").read_text().splitlines()
    cpu = next((line.split(":", 1)[1].strip() for line in cpu_lines if line.startswith("model name")), platform.machine())
    meta = {"utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(), "cpu": cpu,
            "logical_cpus": os.cpu_count(), "build": "release", "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()}
    for number, (players, opponent, seed, slot) in enumerate(scenarios):
        directory = args.out / f"{number:03d}-{players}p-{opponent}-s{seed}-slot{slot}"
        names = [opponent] * players
        names[slot] = "baseline"
        command = [str(runner), "--map", f"maps/arena_{players}p.ron", "--seed", str(seed), "--out", str(directory)]
        for name in names:
            command += ["--ai", str(args.bin_dir / f"libfff_bot_{name}.so")]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        summary = json.loads(result.stdout)
        subprocess.run([str(runner), "verify", str(directory)], check=True, stdout=subprocess.DEVNULL)
        winners = summary["outcome"]["winners"]
        outcome = "W" if winners == [slot] else "D" if slot in winners else "L"
        times = []
        for path in sorted((directory / "frames").glob("*.json")):
            record = json.loads(path.read_text())
            times.append(record["calls"][slot]["elapsed_us"])
        manifest = json.loads((directory / "manifest.json").read_text())
        row = {"players": players, "opponent": opponent, "seed": seed, "slot": slot, "result": outcome,
               "turns": summary["turns"], "scores": summary["scores"],
               "score_difference": summary["scores"][slot] - max(score for i, score in enumerate(summary["scores"]) if i != slot),
               "ai_failures": summary["ai_failures"], "illegal_actions": summary["illegal_actions"],
               "candidate_elapsed_us": times, "manifest": manifest, "directory": str(directory)}
        rows.append(row)
        print(f"{number + 1}/{len(scenarios)} {players}p vs {opponent} seed={seed} slot={slot}: {outcome}, scores={summary['scores']}", flush=True)
    payload = {"environment": meta, "matches": rows}
    (args.out / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["players"], row["opponent"])].append(row)
    lines = ["# 基准 AI 首版实测", "", f"评测时间 UTC：{meta['utc']}。构建：release；CPU：{cpu}；系统：{meta['platform']}。",
             f"来源提交：`{meta['git_commit']}`；各 AI 二进制 SHA-256、实际地图/配置、逐队耗时和原始比赛目录保存在 `{args.out}/report.json`。", "",
             "全部比赛经过同一 C ABI、串行 worker、50ms 预算和标准记录器，随后重新执行引擎验证回放。双队集合使用种子 0–5 并交换出生槽；对等待 AI 使用种子 0–1；3–8 队使用种子 17、候选 AI 轮换全部出生槽，其余均为贪心 AI。", "",
             "| 队伍数 | 对照 | 场次 | 胜/平/负 | 平均分差（候选减最高对手） | 候选耗时 P50/P95/P99（µs） | AI 故障 / 非法动作（全部队伍） |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for (players, opponent), group in sorted(grouped.items()):
        times = [t for row in group for t in row["candidate_elapsed_us"]]
        counts = [sum(row["result"] == label for row in group) for label in ("W", "D", "L")]
        failures = sum(sum(row["ai_failures"]) for row in group)
        invalid = sum(sum(row["illegal_actions"]) for row in group)
        lines.append(f"| {players} | {opponent} | {len(group)} | {'/'.join(map(str, counts))} | {statistics.mean(row['score_difference'] for row in group):.2f} | {percentile(times,50)}/{percentile(times,95)}/{percentile(times,99)} | {failures} / {invalid} |")
    lines += ["", "耗时是裁判侧完整请求墙钟时间，包含恢复、IPC 和返回校验，不是单独策略函数的 CPU 时间；初始化另计。", "",
              "这是一组固定种子的初步基线评估，不能由此宣称对所有 AI/地图达到某个普遍胜率。现有地图存在出生位距离差异，轮换可揭示位置影响，但地图公平性仍需进一步调整。", "",
              "重现：先执行 `cargo build --release --workspace`，再执行 `python3 scripts/evaluate.py --out runs/evaluation-new --report docs/evaluation-new.md`。输出目录必须不存在。"]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.report)

if __name__ == "__main__":
    main()
