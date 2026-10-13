#!/usr/bin/env python3
"""Process-boundary double; records deliberately aren't engine-valid replays.

Real-engine verification is covered by tournament_integration.py. This fixture
checks the orchestrator's argv, identity, recovery and error-handling contract.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys

args=sys.argv[1:]
if args[0]=='verify':
    root=Path(args[1])
    if (root/'bad-verify').exists():
        sys.exit('injected verification failure')
    json.loads((root/'summary.json').read_text())
    print('{"verified":true}')
    sys.exit(0)
values={}
for key,value in zip(args[::2],args[1::2]):
    if key not in ('--map','--out','--seed','--ai','--ai-seed'):
        sys.exit('unexpected argument')
    values.setdefault(key,[]).append(value)
root=Path(values['--out'][0])
root.mkdir()
control=Path(__file__).with_name('control')
if control.exists():
    sys.exit('injected runner error')
n=len(values['--ai'])
assert len(values['--ai-seed'])==n
teams=[{'team_id':i,'name':Path(lib).stem,'library_path':str(Path(lib).resolve()),
        'library_sha256':hashlib.sha256(Path(lib).read_bytes()).hexdigest(),'ai_seed':int(values['--ai-seed'][i])}
       for i,lib in enumerate(values['--ai'])]
manifest={'format_version':1,'match_id':'fixture','engine_version':'0.1.0','rules_version':'fixture',
          'rng_version':'fixture','seed':int(values['--seed'][0]),'config':{'flag_respawn_min_turns':5,'flag_respawn_max_turns':15},
          'map_id':'fixture','teams':teams,'status':'complete','last_complete_turn':1,'time_policy':'fixture',
          'platform':'fixture','build_profile':'fixture'}
summary={'complete':True,'turns':1,'scores':[20]+[0]*(n-1),'outcome':{'reason':'target_score','winners':[0]},
         'ai_failures':[0]*n,'illegal_actions':[0]*n}
(root/'frames').mkdir()
for name,data in [('manifest.json',manifest),('summary.json',summary),('frames/000001.json',
    {'format_version':1,'frame':{'turn':1},'calls':[{'team_id':i,'turn':1,'status':'ok','elapsed_us':10+i,'init_elapsed_us':0,
    'restart_count':0,'actions':None,'raw_output':None,'error':None} for i in range(n)],'call_order':list(range(n))})]:
    (root/name).write_text(json.dumps(data))
shutil.copyfile(values['--map'][0],root/'map.ron')
print(json.dumps(summary))
