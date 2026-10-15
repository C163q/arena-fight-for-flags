"""Artifact tests catch accidental source disclosure and unusable package layouts."""
import hashlib
import importlib.util
import json
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

    def test_wrong_build_profile_or_target_is_rejected(self):
        for key, value in [('profile', 'debug'), ('target', 'aarch64-unknown-linux-gnu')]:
            with self.subTest(key=key):
                info = self.info | {key: value}
                with self.assertRaises(ValueError):
                    package.assemble(self.root, self.artifacts, self.out, info)
                self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
