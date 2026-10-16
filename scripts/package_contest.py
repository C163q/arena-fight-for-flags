"""Build release tools and publish a source-free contest kit (Linux x86_64 GNU)."""
import argparse
import ctypes
import errno
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

TARGET = 'x86_64-unknown-linux-gnu'
BINARIES = ('fff-runner', 'fff-ai-worker', 'fff-timer-query')
TOURNAMENT_FILES = ('__init__.py', 'execution.py', 'launch.py', 'reporting.py', 'schedule.py', 'storage.py', 'seeds.py')
VIEWER_FILES = ('export.py', 'schema.py', 'index.html', 'player.css', 'player.js')
DOC_FILES = ('README.md', 'docs/rules.md', 'docs/api.md', 'docs/testing.md', 'docs/replay.md')


def checked_file(base, relative):
    base = base.resolve(strict=True)
    path = base / relative
    for part in (path, *path.parents):
        if part == base:
            break
        if part.is_symlink():
            raise ValueError(f'symlink is not allowed: {path}')
    if not path.is_file():
        raise ValueError(f'missing regular file: {path}')
    return path


def check_elf(path):
    with path.open('rb') as stream:
        header = stream.read(64)
    if (len(header) < 64 or header[:6] != b'\x7fELF\x02\x01'
            or int.from_bytes(header[18:20], 'little') != 62
            or int.from_bytes(header[16:18], 'little') not in (2, 3)):
        raise ValueError(f'expected Linux x86_64 ELF executable/shared library: {path}')


def copy_file(source, destination, executable=False):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(0o755 if executable else 0o644)


def validate_release_artifacts(artifacts):
    for name in (*BINARIES, 'fff-timer', 'libfff_bot_baseline.so'):
        path = checked_file(artifacts, name)
        check_elf(path)
        sections = subprocess.check_output(['readelf', '--wide', '--sections', str(path)], text=True)
        if any(section in sections for section in ('.debug_', '.zdebug_', '.symtab')):
            raise ValueError(f'debug/unstripped ELF is not allowed: {path}')
    symbols = subprocess.check_output(
        ['readelf', '--wide', '--dyn-syms', str(artifacts / 'libfff_bot_baseline.so')], text=True)
    exports = set()
    for line in symbols.splitlines():
        fields = line.split()
        if len(fields) == 8 and fields[3] == 'FUNC' and fields[4] in ('GLOBAL', 'WEAK') and fields[6] != 'UND':
            exports.add(fields[7])
    required = {'ctf_abi_version', 'ctf_create', 'ctf_decide', 'ctf_destroy'}
    if not required.issubset(exports):
        raise ValueError(f'baseline ABI exports missing: {sorted(required - exports)}')


def tournament_config():
    ais = [{'id': 'candidate', 'name': '我的 AI', 'library': '../submission/libteam.so'}]
    ais += [{'id': f'baseline_{i}', 'name': f'基准 {i}', 'library': '../lib/libfff_bot_baseline.so'} for i in range(1, 8)]
    return {'version': 1, 'runner': '../bin/fff-runner', 'mode': 'balanced', 'repeats': 5,
            'ais': ais, 'lineups': [
                {'id': f'{n}p', 'players': n, 'map': f'../maps/arena_{n}p.ron',
                 'ais': ['candidate'] + [f'baseline_{i}' for i in range(1, n)]}
                for n in range(2, 9)]}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    path.chmod(0o644)


def publish(stage, output):
    # Linux RENAME_NOREPLACE closes the race between the initial exists check and publication.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(stage), -100, os.fsencode(output), 1) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise ValueError(f'output already exists: {output}')
        raise OSError(code, os.strerror(code), str(output))


def assemble(root: Path, artifacts: Path, output: Path, build_info: dict) -> Path:
    if build_info.get('profile') != 'release' or build_info.get('target') != TARGET:
        raise ValueError('only release x86_64-unknown-linux-gnu artifacts are supported')
    output = output.absolute()
    if os.path.lexists(output):
        raise ValueError(f'output already exists: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{output.name}-', dir=output.parent) as temporary:
        temp = Path(temporary)
        outer = temp / 'outer'
        inner = temp / 'fff-contest'
        outer.mkdir()
        inner.mkdir()
        for name in (*BINARIES, 'fff-timer', 'libfff_bot_baseline.so'):
            source = checked_file(artifacts, name)
            check_elf(source)
            destination = (outer / name if name == 'fff-timer' else
                           inner / 'lib' / name if name.endswith('.so') else inner / 'bin' / name)
            copy_file(source, destination, executable=not name.endswith('.so'))
        sources = [('include/ctf_ai.h', 'include/ctf_ai.h'), ('scripts/tournament.py', 'scripts/tournament.py')]
        sources += [(f'maps/arena_{n}p.ron', f'maps/arena_{n}p.ron') for n in range(2, 9)]
        sources += [(f'scripts/tournament_lib/{name}', f'scripts/tournament_lib/{name}') for name in TOURNAMENT_FILES]
        sources += [(f'viewer/{name}', f'viewer/{name}') for name in VIEWER_FILES]
        sources += [(f'packaging/contest/participant/{name}', name) for name in DOC_FILES]
        for source, destination in sources:
            copy_file(checked_file(root, source), inner / destination)
        (inner / 'config').mkdir()
        write_json(inner / 'config/tournament.example.json', tournament_config())
        files = {p.relative_to(inner).as_posix(): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                 'mode': p.stat().st_mode & 0o777} for p in sorted(inner.rglob('*')) if p.is_file()}
        write_json(inner / 'manifest.json', {'kit_format': 'fff-contest', 'kit_version': 1,
                                           'abi_version': 1, 'build': build_info, 'files': files})
        archive = outer / 'participant.tar.gz'
        with archive.open('wb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as tar:
                    for path in sorted(inner.rglob('*')):
                        if path.is_file():
                            info = tar.gettarinfo(str(path), arcname='fff-contest/' + path.relative_to(inner).as_posix())
                            info.uid = info.gid = 0
                            info.uname = info.gname = ''
                            info.mtime = 0
                            with path.open('rb') as stream:
                                tar.addfile(info, stream)
        archive.chmod(0o644)
        organizer = checked_file(root, 'packaging/contest/organizer/README.md').read_text()
        organizer = organizer.replace('@ARCHIVE_SHA256@', hashlib.sha256(archive.read_bytes()).hexdigest())
        organizer = organizer.replace('@TIMER_SHA256@', hashlib.sha256((outer / 'fff-timer').read_bytes()).hexdigest())
        (outer / 'README.md').write_text(organizer, encoding='utf-8')
        (outer / 'README.md').chmod(0o644)
        publish(outer, output)
    return output


def build_release(root):
    if sys.platform != 'linux' or platform.machine() != 'x86_64' or platform.libc_ver()[0] != 'glibc':
        raise ValueError('packaging requires Linux x86_64 GNU/glibc')
    env = os.environ.copy()
    # A separate cache and explicit Cargo options prevent accidentally shipping stale/debug artifacts.
    for name in ('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'CARGO_BUILD_RUSTFLAGS'):
        env.pop(name, None)
    # Highest-priority encoded flags also override target-specific environment/config rustflags.
    env['CARGO_ENCODED_RUSTFLAGS'] = '\x1f'.join([
        '-C', 'opt-level=3', '-C', 'debuginfo=0', '-C', 'strip=symbols', '-C', 'debug-assertions=off'])
    target_dir = root / 'target/contest-build'
    env['CARGO_TARGET_DIR'] = str(target_dir)
    command = ['cargo', 'build', '--locked', '--release', '--target', TARGET,
               '-p', 'fff-runner', '-p', 'fff-ai-worker', '-p', 'fff-bot-baseline', '-p', 'fff-session-timer',
               '--config', 'profile.release.opt-level=3', '--config', 'profile.release.debug=0',
               '--config', 'profile.release.strip="symbols"', '--config', 'profile.release.debug-assertions=false']
    subprocess.run(command, cwd=root, env=env, check=True)
    artifacts = target_dir / TARGET / 'release'
    validate_release_artifacts(artifacts)
    glibc_versions = set()
    for name in (*BINARIES, 'fff-timer', 'libfff_bot_baseline.so'):
        result = subprocess.run(['readelf', '--version-info', str(artifacts / name)], capture_output=True, text=True, check=True)
        glibc_versions.update(re.findall(r'GLIBC_(\d+(?:\.\d+)+)', result.stdout))
    info = {'profile': 'release', 'target': TARGET,
            'rustc': subprocess.check_output(['rustc', '-vV'], text=True).strip(),
            'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
            'source_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root)),
            'system': platform.platform(),
            'glibc_min': max(glibc_versions, key=lambda v: tuple(map(int, v.split('.')))) if glibc_versions else None,
            'runtime_dependencies': ['glibc', 'libgcc_s.so.1'], 'debug_info': False, 'stripped': True}
    return artifacts, info


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=root / 'dist/contest-kit')
    args = parser.parse_args()
    try:
        if os.path.lexists(args.out):
            raise ValueError(f'output already exists: {args.out}')
        artifacts, info = build_release(root)
        out = assemble(root, artifacts, args.out, info)
        print(json.dumps({'output': str(out), 'archive': str(out / 'participant.tar.gz'), 'build': info}, ensure_ascii=False))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'题包生成失败：{error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
