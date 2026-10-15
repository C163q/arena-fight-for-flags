"""Exercise the real contest tarball outside the repository without starting a timer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]


def check_links(root):
    checked = 0
    for source in root.rglob('*.md'):
        for target in re.findall(r'!?\[[^\]\n]*\]\(([^\s)]+)\)', source.read_text()):
            if re.match(r'[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('#'):
                continue
            path = (source.parent / target.split('#')[0]).resolve()
            assert path.is_relative_to(root) and path.is_file(), (source, target)
            checked += 1
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='new acceptance directory outside the repository')
    args = parser.parse_args()
    out = args.out.resolve()
    if out.is_relative_to(ROOT) or ROOT.is_relative_to(out):
        parser.error('--out must be outside the repository')
    if out.exists():
        parser.error('--out already exists')
    out.mkdir(parents=True)
    started = time.monotonic()
    archive_path = args.kit.resolve() / 'participant.tar.gz'
    with tarfile.open(archive_path) as tar:
        seen = set()
        for member in tar.getmembers():
            path = Path(member.name)
            assert member.isfile() and path.parts[0] == 'fff-contest' and not path.is_absolute() and '..' not in path.parts
            assert member.name not in seen
            seen.add(member.name)
            destination = out / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, destination.open('xb') as target:
                shutil.copyfileobj(source, target)
            destination.chmod(member.mode & 0o755)
    root = out / 'fff-contest'
    manifest = json.loads((root / 'manifest.json').read_text())
    for relative, info in manifest['files'].items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == info['sha256']
    links = check_links(root)
    forbidden = [p for p in root.rglob('*') if p.name == 'fff-timer' or p.suffix in ('.rs', '.rlib', '.c', '.cpp', '.pyc')]
    assert not forbidden, forbidden
    # Test-only implementations copied after the shipped file list has been inspected.
    work = root / 'submission'
    work.mkdir()
    shutil.copy(ROOT / 'tests/fixtures/contest_wait.c', work / 'test.c')
    shutil.copy(ROOT / 'tests/fixtures/contest_wait.rs', work / 'test.rs')
    logs = out / 'logs'
    logs.mkdir()
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    calls = []
    def run(name, command, codes=(0,)):
        result = subprocess.run([str(x) for x in command], cwd=root, env=env, capture_output=True, text=True, timeout=180)
        (logs / f'{name}.stdout').write_text(result.stdout)
        (logs / f'{name}.stderr').write_text(result.stderr)
        assert result.returncode in codes, (name, result.returncode, result.stderr[-2000:])
        calls.append({'name': name, 'exit_code': result.returncode})
        return result
    run('c-build', ['cc', '-std=c11', '-O2', '-shared', '-fPIC', '-Werror', '-Iinclude', 'submission/test.c', '-o', 'submission/libc_team.so'])
    run('rust-build', ['rustc', '--edition=2024', '--crate-type=cdylib', '-O', 'submission/test.rs', '-o', 'submission/libteam.so'])
    symbols = run('symbols', ['nm', '-D', '--defined-only', 'submission/libteam.so']).stdout
    for symbol in ('ctf_abi_version', 'ctf_create', 'ctf_decide', 'ctf_destroy'):
        assert re.search(r'\b' + symbol + r'$', symbols, re.M)
    run('runner-help', ['bin/fff-runner', '--help'])
    plans = run('plans-2-to-8', [sys.executable, 'scripts/tournament.py', 'plan', '--config', 'config/tournament.example.json',
                              '--out', 'runs/planned', '--mode', 'quick', '--repeats', '1'])
    assert json.loads(plans.stdout)['planned_matches'] == 35
    run('duel-plan', [sys.executable, 'scripts/tournament.py', 'plan', '--config', 'config/tournament.example.json',
                     '--out', 'runs/duel', '--only', '2p', '--mode', 'balanced', '--repeats', '1'])
    run('duel-first', [sys.executable, 'scripts/tournament.py', 'run', 'runs/duel', '--max-matches', '1'])
    partial = json.loads((root / 'runs/duel/results.json').read_text())
    assert partial['completed_matches'] == 1
    run('duel-resume', [sys.executable, 'scripts/tournament.py', 'run', 'runs/duel'])
    run('duel-report', [sys.executable, 'scripts/tournament.py', 'report', 'runs/duel'])
    result = json.loads((root / 'runs/duel/results.json').read_text())
    assert result['completed_matches'] == 2
    run('c-vs-rust', ['bin/fff-runner', '--map', 'maps/arena_2p.ron', '--ai', 'submission/libc_team.so',
                     '--ai', 'submission/libteam.so', '--seed', '41', '--out', 'runs/c-vs-rust'])
    run('c-vs-rust-verify', ['bin/fff-runner', 'verify', 'runs/c-vs-rust'])
    run('eight-teams', ['bin/fff-runner', '--map', 'maps/arena_8p.ron', '--ai', 'submission/libc_team.so',
                       *[item for _ in range(7) for item in ('--ai', 'lib/libfff_bot_baseline.so')],
                       '--seed', '43', '--out', 'runs/eight-teams'])
    run('eight-verify', ['bin/fff-runner', 'verify', 'runs/eight-teams'])
    run('export', [sys.executable, 'viewer/export.py', 'runs/eight-teams'])
    bundle = json.loads((root / 'runs/eight-teams/replay.json').read_text())
    assert bundle['bundle_format'] == 'fff-replay' and bundle['bundle_version'] == 1
    assert (root / 'runs/eight-teams/replay.html').stat().st_size > 1000
    faults = []
    for path in root.glob('runs/**/summary.json'):
        summary = json.loads(path.read_text())
        assert not any(summary['ai_failures']) and not any(summary['illegal_actions']), (path, summary)
        faults.append({'match': str(path.parent.relative_to(root)), 'turns': summary['turns']})
    assert len(faults) == 4
    query = run('timer-query', ['bin/fff-timer-query'], codes=(0, 1))
    if query.returncode == 0:
        assert re.fullmatch(r'\d\d:\d\d:\d\d\n', query.stdout)
    else:
        assert not query.stdout and '不存在' in query.stderr
    report = {'passed': True, 'kit_sha256': hashlib.sha256(archive_path.read_bytes()).hexdigest(),
              'elapsed_seconds': time.monotonic() - started, 'shipped_files': len(seen), 'local_links': links,
              'build': manifest['build'], 'calls': calls, 'matches': faults,
              'timer_query_exit': query.returncode, 'timer_started': False, 'root': str(root)}
    (out / 'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
