"""Artifact tests catch accidental source disclosure and unusable package layouts."""
import hashlib
import json
import os
import subprocess
from unittest.mock import patch
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    import package_contest as package
except ModuleNotFoundError:
    package = None


class ContestPackageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(package, 'contest packager has not been implemented')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent / 'repo'
        for directory in ('packaging', 'maps', 'include', 'viewer'):
            shutil.copytree(ROOT / directory, self.root / directory)
        (self.root / 'scripts').mkdir()
        shutil.copy(ROOT / 'scripts/tournament.py', self.root / 'scripts/tournament.py')
        shutil.copytree(ROOT / 'scripts/tournament_lib', self.root / 'scripts/tournament_lib')
        self.artifacts = self.parent / 'release'
        self.artifacts.mkdir()
        # Real ELF bytes exercise format checks; executable ABI is tested independently.
        for name in ('fff-runner', 'fff-ai-worker', 'fff-timer', 'fff-timer-query', 'libfff_bot_baseline.so'):
            shutil.copyfile('/bin/true', self.artifacts / name)
        self.info = {'profile': 'release', 'target': 'x86_64-unknown-linux-gnu',
                     'rustc': 'fixture', 'source_commit': 'fixture', 'system': 'fixture'}
        self.out = self.parent / 'kit'

    def assemble(self):
        return package.assemble(self.root, self.artifacts, self.out, self.info)

    def test_archive_is_self_contained_and_only_discloses_allowed_files(self):
        # A recursive copy would leak these extra files.
        (self.root / 'viewer/secret.rs').write_text('private strategy')
        (self.root / 'scripts/tournament_lib/secret.py').write_text('private')
        self.assemble()
        self.assertEqual({p.name for p in self.out.iterdir()}, {'README.md', 'fff-timer', 'participant.tar.gz'})
        self.assertTrue((self.out / 'fff-timer').stat().st_mode & 0o111)
        with tarfile.open(self.out / 'participant.tar.gz') as archive:
            files = {m.name: m for m in archive.getmembers() if m.isfile()}
            self.assertTrue(all(p.startswith('fff-contest/') for p in files))
            self.assertIn('fff-contest/include/ctf_ai.h', files)
            self.assertIn('fff-contest/bin/fff-timer-query', files)
            self.assertIn('fff-contest/viewer/player.js', files)
            self.assertFalse(any(p.endswith(('fff-timer', '.rs', '.rlib', 'secret.py', '.pyc')) for p in files))
            self.assertFalse(any('/__pycache__/' in p for p in files))
            manifest = json.load(archive.extractfile('fff-contest/manifest.json'))
            self.assertEqual(manifest['build']['profile'], 'release')
            self.assertEqual(set(manifest['files']), {p.removeprefix('fff-contest/') for p in files} - {'manifest.json'})
            for path, expected in manifest['files'].items():
                member = files['fff-contest/' + path]
                self.assertEqual(hashlib.sha256(archive.extractfile(member).read()).hexdigest(), expected['sha256'])
                self.assertEqual(member.mode, expected['mode'])
                self.assertFalse(member.name.startswith('/') or '..' in Path(member.name).parts)
            config = json.load(archive.extractfile('fff-contest/config/tournament.example.json'))
            self.assertEqual(config['runner'], '../bin/fff-runner')
            self.assertEqual([l['players'] for l in config['lineups']], list(range(2, 9)))
            self.assertEqual(config['ais'][0]['library'], '../submission/libteam.so')
            self.assertTrue(all(ai['library'] == '../lib/libfff_bot_baseline.so' for ai in config['ais'][1:]))

    def test_repeated_packaging_has_stable_archive_bytes(self):
        self.assemble()
        first = (self.out / 'participant.tar.gz').read_bytes()
        self.out = self.parent / 'other-kit'
        self.assemble()
        self.assertEqual(first, (self.out / 'participant.tar.gz').read_bytes())

    def test_existing_output_is_never_replaced(self):
        self.out.mkdir()
        (self.out / 'keep').write_text('human data')
        with self.assertRaisesRegex(ValueError, 'exists'):
            self.assemble()
        self.assertEqual((self.out / 'keep').read_text(), 'human data')
        self.assertEqual({p.name for p in self.out.iterdir()}, {'keep'})

    def test_missing_artifact_does_not_publish_or_leave_staging(self):
        (self.artifacts / 'libfff_bot_baseline.so').unlink()
        before = set(self.parent.iterdir())
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.assemble()
        self.assertEqual(set(self.parent.iterdir()), before)
        self.assertFalse(self.out.exists())

    def test_artifact_symlink_is_rejected_without_touching_target(self):
        target = self.parent / 'protected'
        target.write_bytes(Path('/bin/true').read_bytes())
        path = self.artifacts / 'fff-timer'
        path.unlink()
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.assemble()
        self.assertTrue(target.is_file())
        self.assertFalse(self.out.exists())

    def test_source_directory_symlink_is_rejected(self):
        target = self.parent / 'headers'
        (self.root / 'include').rename(target)
        (self.root / 'include').symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.assemble()
        self.assertFalse(self.out.exists())

    def test_non_elf_artifact_is_rejected(self):
        (self.artifacts / 'fff-runner').write_text('#!/bin/sh\nexit 0\n')
        with self.assertRaisesRegex(ValueError, 'ELF'):
            self.assemble()
        self.assertFalse(self.out.exists())

    def test_target_rustflags_cannot_reenable_debug_or_disable_stripping(self):
        # Exercise real Cargo/rustc, not a mock of flag ordering.
        members = ('runner', 'worker', 'baseline', 'timer')
        (self.root / 'Cargo.toml').write_text('[workspace]\nmembers = ["runner","worker","baseline","timer"]\nresolver="3"\n')
        packages = ('fff-runner', 'fff-ai-worker', 'fff-bot-baseline', 'fff-session-timer')
        for member, name in zip(members, packages):
            directory = self.root / member
            directory.mkdir()
            text = f'[package]\nname="{name}"\nversion="0.1.0"\nedition="2024"\n'
            if member == 'baseline':
                text += '[lib]\ncrate-type=["cdylib"]\npath="lib.rs"\n'
                (directory / 'lib.rs').write_text('\n'.join(f'#[unsafe(no_mangle)] pub extern "C" fn {symbol}()->u32{{1}}' for symbol in ('ctf_abi_version','ctf_create','ctf_decide','ctf_destroy')))
            elif member == 'timer':
                for binary in ('fff-timer', 'fff-timer-query'):
                    text += f'[[bin]]\nname="{binary}"\npath="{binary}.rs"\n'
                    (directory / f'{binary}.rs').write_text('fn main() {}\n')
            else:
                text += '[[bin]]\nname="' + name + '"\npath="main.rs"\n'
                (directory / 'main.rs').write_text('fn main() {}\n')
            (directory / 'Cargo.toml').write_text(text)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'fixture'], check=True)
        subprocess.run(['cargo', 'generate-lockfile', '--offline'], cwd=self.root, check=True)
        (self.root / '.cargo').mkdir()
        (self.root / '.cargo/config.toml').write_text(
            '[target.x86_64-unknown-linux-gnu]\nrustflags=["-C","debuginfo=2","-C","strip=none","-C","opt-level=0"]\n')
        with patch.dict(os.environ, {'CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUSTFLAGS':
                                    '-C debuginfo=2 -C strip=none -C opt-level=0'}):
            artifacts, info = package.build_release(self.root)
        sections = subprocess.check_output(['readelf', '-S', str(artifacts / 'fff-runner')], text=True)
        self.assertNotIn('.debug_info', sections)
        self.assertNotIn('.symtab', sections)
        self.assertEqual(info['profile'], 'release')

    def test_debug_elf_is_rejected_before_publication(self):
        self.assertTrue(hasattr(package, 'validate_release_artifacts'), 'missing release artifact verification')
        source = self.parent / 'debug.c'
        source.write_text('int main(void){return 0;}\n')
        subprocess.run(['cc', '-g', str(source), '-o', str(self.artifacts / 'fff-runner')], check=True)
        with self.assertRaisesRegex(ValueError, 'debug|unstripped'):
            package.validate_release_artifacts(self.artifacts)

    def test_missing_baseline_abi_exports_are_rejected(self):
        self.assertTrue(hasattr(package, 'validate_release_artifacts'), 'missing release artifact verification')
        with self.assertRaisesRegex(ValueError, 'ABI'):
            package.validate_release_artifacts(self.artifacts)

    def test_wrong_build_profile_or_target_is_rejected(self):
        for key, value in [('profile', 'debug'), ('target', 'aarch64-unknown-linux-gnu')]:
            with self.subTest(key=key):
                info = self.info | {key: value}
                with self.assertRaises(ValueError):
                    package.assemble(self.root, self.artifacts, self.out, info)
                self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
