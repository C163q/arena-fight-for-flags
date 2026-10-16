"""Boundary fixtures; fake records are not a substitute for real-engine acceptance."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))


class ToolFixture(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.base=Path(temp.name)
        self.runner=self.base/'fff-runner';self.map=self.base/'map.ron';self.ai=self.base/'team.so';self.opponent=self.base/'baseline.so'
        self.ai.write_bytes(b'candidate');self.opponent.write_bytes(b'opponent')
        (self.base/'fff-ai-worker').write_bytes(b'worker');(self.base/'fff-ai-worker').chmod(0o755)
        data={'format_version':1,'id':'arena_2p','players':2,'width':9,'height':9,
              'match_limits':{'max_turns':30,'target_score':20},'terrain':['#########']+['#.......#']*7+['#########'],
              'spawn_regions':[{'team_id':0,'x':1,'y':1,'width':3,'height':3},{'team_id':1,'x':5,'y':5,'width':3,'height':3}],
              'flag_points':[{'id':0,'x':4,'y':4}]}
        (self.base/'map-fixture.json').write_text(json.dumps(data))
        self.map.write_text('(id: "arena_2p", players: 2, match_limits: (max_turns: 30, target_score: 20))')
        source=(ROOT/'tests/fixtures/tournament_runner.py').read_text().split('\n',1)[1]
        inspect='''import re
if sys.argv[1]=='inspect-map':
    data=json.loads(Path(__file__).with_name('map-fixture.json').read_text())
    text=Path(sys.argv[2]).read_text()
    data['match_limits']['max_turns']=int(re.search(r'max_turns\\s*:\\s*(\\d+)',text).group(1))
    print(json.dumps(data));sys.exit(0)
'''
        source=source.replace('args=sys.argv[1:]',''+inspect+'\nargs=sys.argv[1:]')
        self.runner.write_text('#!'+sys.executable+'\n'+source);self.runner.chmod(0o755)
