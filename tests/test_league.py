"""League input freezing and plan contracts, without invoking third-party AIs."""
import copy
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from tournament_lib.league_storage import create_league_plan
from tournament_lib.storage import load_plan


class LeaguePlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base/'bot.so').write_bytes(b'library')
        (self.base/'fff-runner').write_text('#!'+sys.executable+'\nimport json,sys\nfrom pathlib import Path\nassert sys.argv[1]=="inspect-map"\nprint(Path(sys.argv[2]).read_text())\n')
        (self.base/'fff-runner').chmod(0o755)
        (self.base/'fff-ai-worker').write_text('worker')
        (self.base/'fff-ai-worker').chmod(0o755)
        for n in (2,4):
            (self.base/f'{n}.ron').write_text(json.dumps({'players':n}))
        self.cfg = {'version':2,'runner':'fff-runner','participants':[
            {'id':c,'library':'bot.so'} for c in ('a','b','c')],
            'filler':{'name':'基准','library':'bot.so'},
            'maps':[{'id':f'm{n}','map':f'{n}.ron'} for n in (2,4)]}
        self.out = self.base/'out'

    def make(self, cfg=None, **kwargs):
        path = self.base/'config.json'
        path.write_text(json.dumps(self.cfg if cfg is None else cfg))
        return create_league_plan(path,self.out,**kwargs)

    def test_automatic_capacity_filling_and_frozen_identities(self):
        plan = self.make(repeats=2)
        self.assertEqual(plan['version'],2)
        self.assertEqual(plan['participants'],['a','b','c'])
        self.assertEqual([g['players'] for g in plan['groups']],[2,4])
        self.assertEqual(len(plan['matches']),36)
        self.assertEqual(len(plan['blocks']),4)
        self.assertEqual(load_plan(self.out),plan)
        for block in plan['blocks']:
            rows = [m for m in plan['matches'] if m['block']==block['id']]
            self.assertEqual({m['engine_seed'] for m in rows},{block['engine_seed']})
            for row in rows:
                self.assertEqual(row['ai_seeds'],[block['ai_seeds'][a] for a in row['slots']])
                self.assertEqual(len(row['slots']),len(set(row['slots'])))
        filler = [a for a in plan['ais'] if a['id'] not in plan['participants']]
        self.assertEqual(len(filler),1)
        self.assertEqual(filler[0]['role'],'filler')
        (self.base/'bot.so').write_bytes(b'new source')
        self.assertEqual(load_plan(self.out),plan)
        (self.out/plan['ais'][0]['path']).write_bytes(b'tampered frozen input')
        with self.assertRaisesRegex(ValueError,'fingerprint'):
            load_plan(self.out)

    def test_reject_invalid_config_without_publishing(self):
        mutations = [lambda c:c.update(participants=[]),lambda c:c.update(repeats=True),
                     lambda c:c['participants'].append(c['participants'][0]),
                     lambda c:c['maps'].append(c['maps'][0]),lambda c:c.pop('filler'),
                     lambda c:c.update(version=1),lambda c:c['participants'][0].update(id='../bad')]
        for mutate in mutations:
            cfg = copy.deepcopy(self.cfg)
            mutate(cfg)
            with self.subTest(cfg=cfg),self.assertRaises(ValueError):
                self.make(cfg)
            self.assertFalse(self.out.exists())
        with self.assertRaisesRegex(ValueError,'limit'):
            self.make(match_limit=2)
        self.assertFalse(self.out.exists())

    def test_only_maps_and_no_unneeded_filler(self):
        self.cfg.pop('filler')
        plan = self.make(only=['m2'])
        self.assertEqual(len(plan['matches']),6)
        self.assertEqual(len(plan['ais']),3)
        with self.assertRaises(ValueError):
            self.make(only=['missing'])

    def test_invalid_inspected_capacity_is_rejected_before_publish(self):
        (self.base/'2.ron').write_text('{"players":true}')
        with self.assertRaises(ValueError):
            self.make()
        self.assertFalse(self.out.exists())

    def test_inspection_uses_snapshot_not_mutable_source(self):
        runner = self.base/'fff-runner'
        runner.write_text(runner.read_text().replace('print(Path(sys.argv[2]).read_text())',
            'assert "/inputs/maps/" in sys.argv[2]\nprint(Path(sys.argv[2]).read_text())'))
        self.make()

    def test_old_cli_rejects_league_plan_before_starting_matches(self):
        self.make()
        script = Path(__file__).resolve().parents[1]/'scripts/tournament.py'
        for command in ('run','report'):
            result = subprocess.run([sys.executable,str(script),command,str(self.out)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('league.py',result.stderr)
            self.assertFalse((self.out/'matches').exists())
