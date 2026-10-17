"""Real release acceptance for frozen small tests, comparisons and backups."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

REPO=Path(__file__).resolve().parents[1]
CLI=REPO/'scripts/selftest.py'

def load(path):return json.loads(path.read_text())
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def invoke(*args,expected=0):
    result=subprocess.run([sys.executable,str(CLI),*map(str,args)],capture_output=True,text=True,timeout=240)
    assert result.returncode==expected,(args,result.returncode,result.stderr[-2000:],result.stdout[-1000:])
    return result

def short_map(destination,turns=2):
    text=(REPO/'maps/arena_2p.ron').read_text()
    destination.write_text(re.sub(r'max_turns:\s*\d+',f'max_turns: {turns}',text))
    return destination

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--bin-dir',type=Path,default=REPO/'target/release')
    args=parser.parse_args();out=args.out.resolve();bins=args.bin_dir.resolve()
    if out.exists():parser.error('output must not exist')
    out.mkdir(parents=True);started=time.monotonic()
    runner=bins/'fff-runner';baseline=bins/'libfff_bot_baseline.so'
    candidate=out/'candidate.so';shutil.copyfile(baseline,candidate)
    defaults=out/'default'
    invoke('run','--ai',candidate,'--runner',runner,'--out',defaults)
    result=load(defaults/'results.json')
    assert result['completed_matches']==result['planned_matches']==2
    assert result['execution']=={'jobs_used':[1],'classification':'serial'}
    small=short_map(out/'short.ron');suite=out/'compare'
    invoke('compare','--ai',f'old={candidate}','--ai',f'new={baseline}',
           '--runner',runner,'--map',small,'--out',suite,'--jobs','2','--max-matches','1')
    assert load(suite/'results.json')['completed_matches']==1
    old=load(suite/'versions/old/plan.json');new=load(suite/'versions/new/plan.json')
    assert old['matches']==new['matches'],'versions must share roles, slots and both seed streams'
    source_sha=digest(candidate);candidate.write_bytes(b'changed after freezing')
    invoke('resume',suite)
    result=load(suite/'results.json');assert result['completed_matches']==4
    assert result['execution']['jobs_used']==[1,2]
    assert result['execution']['classification']=='parallel_self_test'
    assert load(suite/'suite.json')['versions'][0]['library_sha256']==source_sha
    attempt_count=len(list(suite.glob('versions/*/matches/*/attempt-*')))
    invoke('resume',suite)
    assert len(list(suite.glob('versions/*/matches/*/attempt-*')))==attempt_count
    analysis=out/'analysis';invoke('summary',suite,'--runner',runner,'--out',analysis)
    summary=load(analysis/'summary.json');assert len(summary['matches'])==4
    assert len(summary['candidates'])==2
    assert 'rng_state' not in (analysis/'summary.json').read_text()
    archive=out/'records.tar.gz';invoke('archive',suite,'--runner',runner,'--out',archive)
    restored=out/'restored';invoke('restore',archive,'--runner',runner,'--out',restored)
    for file in restored.rglob('*'):
        if file.is_file() and file.name!='.lock':
            original=suite/file.relative_to(restored)
            assert original.is_file() and digest(file)==digest(original),(file,original)
    frozen=suite/'inputs/versions/old.so';original=frozen.read_bytes();frozen.write_bytes(b'corrupt')
    assert 'fingerprint' in invoke('resume',suite,expected=2).stderr
    frozen.write_bytes(original)
    first=next(suite.glob('versions/old/matches/*/attempt-*/match/summary.json'))
    original=first.read_bytes();bad=load(first);bad['scores'][0]+=1;first.write_text(json.dumps(bad))
    invoke('summary',suite,'--runner',runner,'--out',out/'bad-analysis',expected=2)
    assert not (out/'bad-analysis').exists();first.write_bytes(original)
    payload={'passed':True,'default_full_games':2,'comparison_two_turn_games':4,
             'checks':['common seeds and positions','frozen source change','parallel provenance after serial resume',
                       'idempotent resume','public summary candidate aggregation','verified archive round-trip',
                       'frozen input corruption rejected','corrupt replay rejected'],
             'elapsed_seconds':time.monotonic()-started}
    (out/'acceptance.json').write_text(json.dumps(payload,indent=2)+'\n');print(json.dumps(payload),flush=True)

if __name__=='__main__':main()
