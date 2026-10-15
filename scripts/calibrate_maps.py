"""Run serial baseline self-play using the real runner, preserving verifiable records."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
from generate_maps import metrics


def recommend_limits(rows):
    """Only completed target-score games estimate duration; caps are right-censored."""
    if {r['players'] for r in rows} != set(range(2, 9)):
        raise ValueError('need samples for all seven player counts before calibrating defaults')
    limits, previous = {}, 300
    for players in sorted({r['players'] for r in rows}):
        group = [r for r in rows if r['players'] == players]
        if any(r['summary']['outcome']['reason'] != 'target_score' for r in group):
            raise ValueError(f'{players}p has censored games; inspect them before choosing a cap')
        observed = max(r['summary']['turns'] for r in group)
        limit = max(400, previous + 100, math.ceil(observed * 1.35 / 100) * 100)
        limits[players] = limit
        previous = limit
    return limits


def calibration_action_counts(summary, records):
    """After Rust verify, distinguish new death drops from illegal submissions."""
    if any(summary['ai_failures']):
        raise ValueError('AI fault; investigate before calibration')
    dynamic = [0] * len(summary['illegal_actions'])
    for record in records:
        frame = record['frame']
        ground = {(f['location']['position']['x'], f['location']['position']['y'])
                  for f in frame['start']['flags'] if f['location']['state'] == 'ground'}
        for event in frame['events']:
            validation = event.get('validation', 'ok')
            if validation == 'ok':
                continue
            target = event.get('target', {})
            if (event['type'] != 'move' or validation != 'carrying_cannot_enter_flag'
                    or (target.get('x'), target.get('y')) in ground):
                raise ValueError(f'illegal submitted action: {validation}')
            # In an engine-verified move phase, a ground flag absent at START
            # can only have appeared through this turn's shooting/death drops.
            dynamic[event['unit']['team_id']] += 1
    if dynamic != summary['illegal_actions']:
        raise ValueError('invalid-action counts differ from verified events')
    return dynamic


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--bin-dir', type=Path, default=Path('target/release'))
    parser.add_argument('--map-dir', type=Path, default=Path('maps'))
    parser.add_argument('--players', type=int, nargs='+', default=list(range(2, 9)))
    parser.add_argument('--seeds', type=int, nargs='+', default=[7, 41, 97, 211, 509])
    parser.add_argument('--pilot-max-turns', type=int, default=0)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.out.exists() and not args.resume:
        parser.error('output exists; use a new directory or --resume')
    if not set(args.players) <= set(range(2, 9)) or len(set(args.players)) != len(args.players):
        parser.error('players must be distinct values in 2..8')
    if len(set(args.seeds)) != len(args.seeds) or not all(0 <= s < 2**64 for s in args.seeds):
        parser.error('seeds must be distinct u64 values')
    if not 0 <= args.pilot_max_turns <= 1000000:
        parser.error('invalid pilot cap')
    args.out.mkdir(parents=True, exist_ok=True)
    runner = (args.bin_dir / 'fff-runner').resolve()
    library = (args.bin_dir / 'libfff_bot_baseline.so').resolve()
    cpu = next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), platform.machine())
    meta = {'utc': datetime.now(timezone.utc).isoformat(), 'cpu': cpu, 'logical_cpus': os.cpu_count(),
            'platform': platform.platform(), 'build': 'release', 'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
            'ai_sha256': sha(library), 'runner_sha256': sha(runner), 'seeds': args.seeds,
            'pilot_max_turns': args.pilot_max_turns, 'ai_seeds': '1000 + team_id'}
    report_path = args.out / 'report.json'
    if args.resume and report_path.exists():
        previous = json.loads(report_path.read_text())['environment']
        if any(previous[k] != meta[k] for k in ('ai_sha256', 'runner_sha256', 'seeds', 'pilot_max_turns')):
            raise ValueError('resume environment/input mismatch; use a new output directory')
    rows = []
    geometry = {}
    for players in sorted(args.players):
        original = args.map_dir / f'arena_{players}p.ron'
        source = original.read_text()
        if args.pilot_max_turns:
            source, replacements = re.subn(r'(max_turns\s*:\s*)\d+', lambda m: m[1] + str(args.pilot_max_turns), source)
            if replacements != 1:
                raise ValueError(f'{original}: expected exactly one max_turns field')
        played_map = args.out / f'arena_{players}p.ron'
        if played_map.exists() and played_map.read_text() != source:
            raise ValueError(f'{played_map}: changed map; use a new output directory')
        played_map.write_text(source)
        for seed in args.seeds:
            directory = args.out / f'{players}p-s{seed}'
            if directory.exists():
                if not args.resume:
                    raise ValueError(f'existing match: {directory}')
                manifest = json.loads((directory / 'manifest.json').read_text())
                if manifest['seed'] != seed or (directory / 'map.ron').read_text() != source or any(t['library_sha256'] != meta['ai_sha256'] or t['ai_seed'] != 1000 + i for i, t in enumerate(manifest['teams'])):
                    raise ValueError(f'{directory}: resume input mismatch')
                summary = json.loads((directory / 'summary.json').read_text())
            else:
                command = [str(runner), '--map', str(played_map), '--out', str(directory), '--seed', str(seed)]
                for team in range(players):
                    command += ['--ai', str(library), '--ai-seed', str(1000 + team)]
                result = subprocess.run(command, check=True, capture_output=True, text=True)
                summary = json.loads(result.stdout)
            subprocess.run([str(runner), 'verify', str(directory)], check=True, stdout=subprocess.DEVNULL)
            loaded = json.loads((directory / 'map.json').read_text())
            assert loaded['match_limits']['target_score'] == 20, loaded['match_limits']
            geometry[str(players)] = metrics(loaded)
            counts, elapsed = Counter(), []
            frame_files = sorted((directory / 'frames').glob('*.json'))
            for frame in frame_files:
                record = json.loads(frame.read_text())
                counts.update(e['type'] for e in record['frame']['events'])
                elapsed.extend(c['elapsed_us'] for c in record['calls'])
            elapsed.sort()
            row = {'players': players, 'seed': seed, 'summary': summary, 'events': dict(counts),
                   'p99_elapsed_us': elapsed[(len(elapsed) - 1) * 99 // 100] if elapsed else 0,
                   'source_map_sha256': sha(original), 'played_map_sha256': sha(played_map), 'directory': str(directory)}
            row['dynamic_flag_blocked_moves'] = calibration_action_counts(
                summary, (json.loads(frame.read_text()) for frame in frame_files))
            rows.append(row)
            payload = {'environment': meta, 'geometry': geometry, 'matches': rows}
            temporary = args.out / 'report.tmp'
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
            temporary.replace(args.out / 'report.json')
            print(f'{len(rows)}/{len(args.players)*len(args.seeds)} {players}p seed={seed}: {summary["turns"]} turns, {summary["outcome"]["reason"]}, scores={summary["scores"]}', flush=True)
    try:
        payload['recommended_limits'] = recommend_limits(rows)
    except ValueError as error:
        payload['recommendation_error'] = str(error)
    (args.out / 'report.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in payload.items() if k.startswith('recommend')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
