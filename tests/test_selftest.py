"""The development wrapper keeps conditions, snapshots and actual execution provenance."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from contest_tools_fixtures import ToolFixture,ROOT
from tournament_lib.storage import load_plan,locked
try:
    from contest_lib.experiment import prepare_suite,resume_suite,load_suite
except ModuleNotFoundError:
    prepare_suite=resume_suite=load_suite=None


class SelftestTests(ToolFixture):
    def prepare(self,versions=None,**kwargs):
        self.assertIsNotNone(prepare_suite,'selftest experiment module missing')
        return prepare_suite(versions or [('main',self.ai)],[self.map],self.opponent,self.runner,self.base/'suite',**kwargs)

    def test_defaults_are_two_matches(self):
        suite=self.prepare();self.assertEqual(suite['planned_matches'],2)
        self.assertEqual(suite['mode'],'quick');self.assertEqual(suite['repeats'],1)
        p=load_plan(self.base/'suite/versions/main')
        self.assertEqual({tuple(m['slots']) for m in p['matches']},{('candidate','opponent_1'),('opponent_1','candidate')})
        self.assertEqual(suite['format'],'fff-selftest')

    def test_versions_share_conditions_but_have_separate_snapshots(self):
        other=self.base/'other.so';other.write_bytes(b'new version')
        suite=self.prepare([('old',self.ai),('new',other)])
        self.assertEqual(suite['planned_matches'],4)
        old=load_plan(self.base/'suite/versions/old');new=load_plan(self.base/'suite/versions/new')
        self.assertEqual(old['matches'],new['matches'])
        self.assertNotEqual(old['ais'][0]['sha256'],new['ais'][0]['sha256'])
        self.assertTrue((self.base/'suite/seeds.json').is_file())

    def test_partial_parallel_resume_keeps_frozen_libraries_and_provenance(self):
        self.prepare()
        first=resume_suite(self.base/'suite',jobs=2,max_matches=1)
        self.assertEqual(first['completed_matches'],1)
        self.ai.write_bytes(b'changed source')
        second=resume_suite(self.base/'suite',jobs=1)
        self.assertEqual(second['completed_matches'],2)
        self.assertEqual(second['execution']['jobs_used'],[1,2])
        self.assertEqual(second['execution']['classification'],'parallel_self_test')
        p=load_plan(self.base/'suite/versions/main')
        candidate=next(a for a in p['ais'] if a['id']=='candidate')
        self.assertEqual(candidate['sha256'],hashlib.sha256(b'candidate').hexdigest())

    def test_invalid_versions_and_existing_output_are_not_overwritten(self):
        self.assertIsNotNone(prepare_suite)
        for versions in [[('../bad',self.ai)],[('x',self.ai),('x',self.ai)]]:
            with self.assertRaises(ValueError):prepare_suite(versions,[self.map],self.opponent,self.runner,self.base/'bad')
            self.assertFalse((self.base/'bad').exists())
        self.prepare();before=(self.base/'suite/suite.json').read_bytes()
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual((self.base/'suite/suite.json').read_bytes(),before)

    def test_reuse_seed_file_and_reject_wrong_map(self):
        self.prepare();seeds=json.loads((self.base/'suite/seeds.json').read_text())
        other=self.base/'second'
        prepare_suite([('main',self.ai)],[self.map],self.opponent,self.runner,other,seed_spec=seeds)
        self.assertEqual(load_plan(self.base/'suite/versions/main')['matches'],load_plan(other/'versions/main')['matches'])
        self.map.write_text(self.map.read_text()+' // changed')
        with self.assertRaises(ValueError):prepare_suite([('main',self.ai)],[self.map],self.opponent,self.runner,self.base/'bad',seed_spec=seeds)
        self.assertFalse((self.base/'bad').exists())

    def test_inner_active_lock_blocks_resume(self):
        self.prepare()
        with locked(self.base/'suite/versions/main'):
            with self.assertRaisesRegex(ValueError,'locked'):resume_suite(self.base/'suite')

    def test_cli_default_run_and_global_segment_limit(self):
        command=[sys.executable,str(ROOT/'scripts/selftest.py'),'compare','--runner',str(self.runner),
                 '--opponent',str(self.opponent),'--map',str(self.map),'--ai',f'old={self.ai}',
                 '--ai',f'new={self.ai}','--out',str(self.base/'cli'),'--max-matches','1']
        result=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('4',result.stdout)
        d=json.loads((self.base/'cli/results.json').read_text());self.assertEqual(d['completed_matches'],1)
