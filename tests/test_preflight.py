"""Control and candidate phases distinguish environment failures from library failures."""
import json
from pathlib import Path
import subprocess
import sys
from contest_tools_fixtures import ToolFixture,ROOT
try:
    from contest_lib.preflight import check_ai
except ModuleNotFoundError:check_ai=None


class PreflightTests(ToolFixture):
    def setUp(self):
        super().setUp()
        source=self.runner.read_text()
        injected='''faults={'abi':('load_error','unsupported AI ABI version'),'crash':('crash','worker crashed'),
        'timeout':('timeout','decision deadline'),'invalid':('ok',None)}
statuses=[];errors=[]
for library in values['--ai']:
    kind=Path(library).read_text()
    status,error=faults.get(kind,('ok',None))
    if Path(__file__).with_name('deny').exists():status,error='load_error','Operation not permitted (os error 1)'
    statuses.append(status);errors.append(error)
summary['ai_failures']=[int(s!='ok') for s in statuses]
summary['illegal_actions']=[int(Path(l).read_text()=='invalid') for l in values['--ai']]
'''
        source=source.replace("for name,data in [('manifest.json',manifest)",injected+"\nfor name,data in [('manifest.json',manifest)")
        source=source.replace("'status':'ok'","'status':statuses[i]").replace("'error':None","'error':errors[i]")
        self.runner.write_text(source)

    def check(self,name='check'):
        self.assertIsNotNone(check_ai,'preflight missing')
        return check_ai(self.ai,self.runner,self.opponent,self.map,self.base/name)

    def test_control_then_candidate_success_and_private_map(self):
        before=self.map.read_bytes();result=self.check()
        self.assertTrue(result['passed']);self.assertEqual([x['phase'] for x in result['stages']],['environment','candidate'])
        self.assertEqual(self.map.read_bytes(),before)
        self.assertIn('max_turns: 2',(self.base/'check/probe.ron').read_text())

    def test_environment_permission_failure_skips_candidate(self):
        (self.base/'deny').touch();result=self.check()
        self.assertFalse(result['passed']);self.assertEqual(len(result['stages']),1)
        self.assertEqual(result['stages'][0]['category'],'environment_permissions')
        self.assertIn('Operation not permitted',str(result))
        self.assertFalse(list((self.base/'check/candidate').glob('matches/*/attempt-*')))

    def test_control_runner_permission_failure_is_not_blame_on_candidate(self):
        self.runner.write_text(self.runner.read_text().replace('injected runner error','Operation not permitted (os error 1)'))
        (self.base/'control').touch()
        result=self.check()
        self.assertFalse(result['passed'])
        self.assertEqual(result['stages'][0]['category'],'environment_permissions')
        self.assertEqual(len(result['stages']),1)

    def test_candidate_fault_categories_and_original_errors(self):
        for value,want in [('abi','abi_or_symbols'),('crash','crash'),('timeout','timeout')]:
            self.ai.write_text(value);result=self.check('check-'+value)
            self.assertTrue(result['stages'][0]['passed']);self.assertFalse(result['passed'])
            self.assertEqual(result['stages'][1]['category'],want)
            self.assertTrue(result['stages'][1]['errors'])

    def test_game_invalid_is_reported_without_becoming_abi_failure(self):
        self.ai.write_text('invalid');result=self.check()
        self.assertTrue(result['passed']);self.assertEqual(result['stages'][1]['illegal_actions'],1)

    def test_cli_failure_is_one_and_invalid_input_is_two(self):
        command=[sys.executable,str(ROOT/'scripts/selftest.py'),'check','--runner',str(self.runner),
                 '--opponent',str(self.opponent),'--map',str(self.map),'--ai',str(self.ai)]
        self.ai.write_text('abi')
        r=subprocess.run(command+['--out',str(self.base/'cli')],capture_output=True,text=True)
        self.assertEqual(r.returncode,1,r.stderr)
        r=subprocess.run(command+['--out',str(self.base/'cli')],capture_output=True,text=True)
        self.assertEqual(r.returncode,2)
        self.assertFalse(json.loads((self.base/'cli/diagnostics.json').read_text())['passed'])
