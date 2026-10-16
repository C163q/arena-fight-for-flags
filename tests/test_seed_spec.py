"""Reusing seeds controls comparisons without replacing immutable inputs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from test_tournament import PlanFixture
from tournament_lib import storage


class SeedSpecTests(PlanFixture):
    def seeds(self):
        return {'version':1,'ai_seed_root':123,'schedule_seed_root':456,
                'maps':{'duel':{'players':2,'sha256':hashlib.sha256((self.base/'map.ron').read_bytes()).hexdigest(),
                                'engine_seeds':[41,73]}}}

    def test_reused_conditions_freeze_different_binaries(self):
        first=self.make(seed_spec=self.seeds())
        (self.base/'shared.so').write_bytes(b'new library')
        second=storage.create_plan(self.config_path,self.base/'other',seed_spec=self.seeds())
        self.assertEqual(first['matches'],second['matches'])
        self.assertEqual([b['engine_seed'] for b in first['blocks']],[41,73])
        self.assertNotEqual(first['ais'][0]['sha256'],second['ais'][0]['sha256'])
        self.assertEqual(storage.load_plan(self.root),first)
        for block in first['blocks']:
            self.assertNotEqual(block['ai_seeds']['a'],block['ai_seeds']['b'])

    def test_invalid_seed_data_never_publishes(self):
        changes=[lambda s:s.update(version=True),lambda s:s.update(ai_seed_root=True),
                 lambda s:s.update(ai_seed_root=2**256),lambda s:s.update(schedule_seed_root=-1),
                 lambda s:s['maps']['duel'].update(engine_seeds=[41,True]),
                 lambda s:s['maps']['duel'].update(engine_seeds=[41,2**64]),
                 lambda s:s['maps']['duel'].update(engine_seeds=[41,41]),
                 lambda s:s['maps']['duel'].update(engine_seeds=[41]),
                 lambda s:s['maps']['duel'].update(players=3),
                 lambda s:s['maps']['duel'].update(sha256='0'*64),
                 lambda s:s.update(maps={})]
        for change in changes:
            s=self.seeds();change(s)
            with self.subTest(s=s),self.assertRaises(ValueError):self.make(seed_spec=s)
            self.assertFalse(self.root.exists())
            self.assertEqual(list(self.base.glob('.output-*')),[])

    def test_copy_failure_leaves_no_output(self):
        with patch.object(storage.shutil,'copyfile',side_effect=OSError('copy failure')):
            with self.assertRaises(OSError):self.make()
        self.assertFalse(self.root.exists())
        self.assertEqual(list(self.base.glob('.output-*')),[])

    def test_copied_map_must_match_explicit_seed_fingerprint(self):
        real=storage.shutil.copyfile
        def changed(source,destination):
            result=real(source,destination)
            if Path(destination).parent.name=='maps':Path(destination).write_text('changed map')
            return result
        with patch.object(storage.shutil,'copyfile',side_effect=changed):
            with self.assertRaises(ValueError):self.make(seed_spec=self.seeds())
        self.assertFalse(self.root.exists())

    def test_existing_and_dangling_outputs_are_not_replaced(self):
        target=self.base/'missing-protected'
        self.root.symlink_to(target,target_is_directory=True)
        with self.assertRaises(ValueError):self.make()
        self.assertTrue(self.root.is_symlink())
        self.assertFalse(target.exists())

    def test_concurrent_destination_creation_keeps_human_file(self):
        original=storage.publish_path
        def race(stage,out):
            Path(out).mkdir();(Path(out)/'keep').write_text('human data')
            return original(stage,out)
        with patch.object(storage,'publish_path',side_effect=race):
            with self.assertRaises(ValueError):self.make()
        self.assertEqual((self.root/'keep').read_text(),'human data')
        self.assertEqual(list(self.root.iterdir()),[self.root/'keep'])

    def test_cli_accepts_seed_file(self):
        self.config_path.write_text(json.dumps(self.config))
        seeds=self.base/'seeds.json';seeds.write_text(json.dumps(self.seeds()))
        command=[sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/tournament.py'),'plan',
                 '--config',str(self.config_path),'--out',str(self.root),'--seed-file',str(seeds)]
        result=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([b['engine_seed'] for b in storage.load_plan(self.root)['blocks']],[41,73])
