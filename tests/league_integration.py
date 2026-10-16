"""Real release-runner acceptance of auto-filled and oversubscribed leagues."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
CLI = REPO/'scripts/league.py'


def load(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--bin-dir',type=Path,default=REPO/'target/release')
    args = parser.parse_args()
    out,bins = args.out.resolve(),args.bin_dir.resolve()
    if out.exists():
        parser.error('output must not exist')
    out.mkdir(parents=True)
    started = time.monotonic()
    calls = []
    def invoke(*argv,expected=0):
        result = subprocess.run([sys.executable,str(CLI),*map(str,argv)],capture_output=True,text=True,timeout=180)
        prefix = out/f'command-{len(calls):02d}'
        prefix.with_suffix('.stdout.log').write_text(result.stdout)
        prefix.with_suffix('.stderr.log').write_text(result.stderr)
        calls.append({'args':list(map(str,argv)),'exit':result.returncode})
        assert result.returncode==expected,(argv,result.returncode,result.stderr[-1500:])
        return result
    maps = []
    for n in (2,3,4,8):
        path = out/f'short-{n}p.ron'
        raw = (REPO/f'maps/arena_{n}p.ron').read_text()
        # Copies only: original gameplay assets and score targets stay untouched.
        import re
        path.write_text(re.sub(r'max_turns: \d+', 'max_turns: 2',raw))
        maps.append({'id':f'm{n}','map':str(path)})
    cfg = {'version':2,'runner':str(bins/'fff-runner'),'repeats':2,
        'participants':[{'id':f'bot{i}','library':str(bins/'libfff_bot_wait.so')} for i in range(3)],
        'filler':{'name':'等待填充','library':str(bins/'libfff_bot_wait.so')},'maps':maps}
    config = out/'config.json'
    config.write_text(json.dumps(cfg))
    root = out/'league'
    invoke('plan','--config',config,'--out',root)
    assert len(load(root/'plan.json')['matches'])==160
    invoke('run',root,'--max-matches',1,'--jobs',2)
    partial = load(root/'results.json')
    assert not partial['overall']['standings'] and not any(g['standings'] for g in partial['groups'])
    first = root/partial['matches'][0]['directory']
    before = (first/'summary.json').stat().st_mtime_ns
    invoke('run',root,'--max-matches',5)
    partial = load(root/'results.json')
    assert partial['groups'][0]['complete_blocks']==1 and not partial['overall']['standings']
    invoke('run',root)
    result = load(root/'results.json')
    assert result['completed_matches']==160 and result['overall']['complete_repeats']==[0,1]
    assert result['execution']['classification']=='parallel_self_test' and result['execution']['jobs_used']==[1,2]
    assert all(x['rank']==1 and x['rank_score']==.5 for x in result['overall']['standings'])
    assert all(len(g['standings'])==3 for g in result['groups'])
    assert (first/'summary.json').stat().st_mtime_ns==before
    count = len(list((root/'matches').glob('*/attempt-*')))
    invoke('run',root)
    assert len(list((root/'matches').glob('*/attempt-*')))==count
    invoke('report',root)
    # Damaged originals cannot be adopted, even if a report/checkpoint exists.
    original = (first/'summary.json').read_bytes()
    meta_path = first.parent/'attempt.json'
    original_meta = meta_path.read_bytes()
    summary = load(first/'summary.json')
    summary['scores'][0] += 1
    (first/'summary.json').write_text(json.dumps(summary))
    error = invoke('report',root,expected=1)
    assert 'verification failed' in error.stderr
    (first/'summary.json').write_bytes(original)
    meta_path.write_bytes(original_meta)
    invoke('report',root)
    cfg['participants'] = cfg['participants'][:1]
    cfg['maps'] = maps[-1:]
    cfg['repeats'] = 1
    config.write_text(json.dumps(cfg))
    solo = out/'solo'
    invoke('plan','--config',config,'--out',solo)
    invoke('run',solo)
    single = load(solo/'results.json')
    assert len(single['overall']['standings'])==1 and single['overall']['standings'][0]['rank_score']==.5
    assert len(load(solo/'plan.json')['ais'])==8
    # Joint 16/8 construction through the actual CLI, then two real matches.
    cfg['participants'] = [{'id':f'bot{i}','library':str(bins/'libfff_bot_wait.so')} for i in range(16)]
    config.write_text(json.dumps(cfg))
    sixteen = out/'sixteen'
    invoke('plan','--config',config,'--out',sixteen)
    assert len(load(sixteen/'plan.json')['matches'])==240
    invoke('run',sixteen,'--max-matches',2)
    sixteen_result = load(sixteen/'results.json')
    assert not sixteen_result['overall']['standings']
    all_rows = result['matches']+single['matches']+sixteen_result['matches']
    assert len(all_rows)==218
    assert all(not any(r['summary']['ai_failures']) and not any(r['summary']['illegal_actions']) for r in all_rows)
    payload = {'passed':True,'completed_matches':len(all_rows),'commands':len(calls),
        'seconds':time.monotonic()-started,'auto_fill':True,'oversubscribed':True,'all_map_completion':True,
        'mixed_jobs_retained':True,'resume_verified':True,'corrupt_replay_rejected':True,'faults':0,'illegal_actions':0}
    (out/'acceptance.json').write_text(json.dumps(payload,indent=2)+'\n')
    print(json.dumps(payload),flush=True)


if __name__=='__main__':
    main()
