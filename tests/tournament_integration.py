"""Exercise tournament CLI with real release workers, maps and replay verification."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
CLI = REPO/'scripts/tournament.py'


def invoke(*args, expected=0):
    result = subprocess.run([sys.executable,str(CLI),*map(str,args)],capture_output=True,text=True)
    if result.returncode != expected:
        raise AssertionError(f'CLI exit {result.returncode}, expected {expected}: {result.stderr}\n{result.stdout[-1500:]}')
    return result


def load(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--bin-dir',type=Path,default=REPO/'target/release')
    args = parser.parse_args()
    out, bins = args.out.resolve(),args.bin_dir.resolve()
    if out.exists():
        parser.error('output must not exist')
    out.mkdir(parents=True)
    started = time.monotonic()
    cfg = {'version':1,'runner':str(bins/'fff-runner'),'mode':'quick','repeats':1,
           'ais':[{'id':f'bot{i}','name':f'基准副本 {i}','library':str(bins/'libfff_bot_baseline.so')} for i in range(8)],
           'lineups':[{'id':f'{n}p','players':n,'map':str(REPO/f'maps/arena_{n}p.ron'),
                       'ais':[f'bot{i}' for i in range(n)]} for n in range(2,9)]}
    config = out/'config.json'
    config.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
    quick = out/'quick'
    invoke('plan','--config',config,'--out',quick)
    assert len(load(quick/'plan.json')['matches']) == 35
    # Interrupt a real live match, rather than only creating a synthetic partial folder.
    with (out/'interrupt.stdout.log').open('w') as stdout, (out/'interrupt.stderr.log').open('w') as stderr:
        process = subprocess.Popen([sys.executable,str(CLI),'run',str(quick),'--max-matches','1'],stdout=stdout,stderr=stderr)
        try:
            deadline = time.monotonic()+15
            manifests=[]
            while time.monotonic() < deadline:
                manifests=list((quick/'matches').glob('*/attempt-000/match/manifest.json'))
                if manifests:
                    try:
                        if load(manifests[0])['status'] == 'in_progress':
                            break
                    except ValueError:
                        pass
                if process.poll() is not None:
                    raise AssertionError('match finished before interruption could be exercised')
                time.sleep(.005)
            else:
                raise AssertionError('runner did not start within 15 seconds')
            process.send_signal(signal.SIGINT)
            assert process.wait(timeout=10) == 130
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    interrupted=manifests[0].parents[1]
    assert load(interrupted/'attempt.json')['state']=='interrupted'
    invoke('run',quick,'--max-matches','1')
    partial=load(quick/'results.json')
    assert partial['completed_matches']==1 and all(not g['standings'] for g in partial['groups'])
    first=quick/partial['matches'][0]['directory']
    before=(first/'summary.json').stat().st_mtime_ns
    invoke('run',quick)
    assert (first/'summary.json').stat().st_mtime_ns==before
    assert interrupted.is_dir() and (interrupted.parent/'attempt-001/match/summary.json').is_file()
    finished=load(quick/'results.json')
    assert finished['completed_matches']==35
    assert all(g['complete_blocks']==1 and g['ranked_matches']==g['players'] for g in finished['groups'])
    before_attempts=len(list((quick/'matches').glob('*/attempt-*')))
    invoke('run',quick)
    assert len(list((quick/'matches').glob('*/attempt-*')))==before_attempts
    # Corrupt a complete real replay, assert verification fails, restore only this test's files.
    summary_bytes=(first/'summary.json').read_bytes()
    meta_path=first.parent/'attempt.json'
    meta_bytes=meta_path.read_bytes()
    summary=load(first/'summary.json')
    summary['scores'][0]+=1
    (first/'summary.json').write_text(json.dumps(summary))
    error=invoke('report',quick,expected=1)
    assert 'verification failed' in error.stderr
    assert load(meta_path)['state']=='invalid'
    (first/'summary.json').write_bytes(summary_bytes)
    meta_path.write_bytes(meta_bytes)
    # Frozen input mismatch is rejected before another match or report is accepted.
    ai=quick/load(quick/'plan.json')['ais'][0]['path']
    ai_bytes=ai.read_bytes()
    ai.write_bytes(ai_bytes+b'changed')
    assert 'fingerprint' in invoke('run',quick,expected=1).stderr
    ai.write_bytes(ai_bytes)
    invoke('report',quick)
    print('Quick 2..8, interruption/resume, corrupt replay and frozen-input checks passed',flush=True)
    balanced=out/'balanced-8p'
    invoke('plan','--config',config,'--out',balanced,'--mode','balanced','--only','8p')
    assert len(load(balanced/'plan.json')['matches'])==56
    invoke('run',balanced)
    formal=load(balanced/'results.json')
    group=formal['groups'][0]
    assert formal['completed_matches']==56 and group['complete_blocks']==1
    for item in group['standings']:
        assert item['matches']==56 and {s['matches'] for s in item['by_slot']}=={7}
    for result in (finished,formal):
        assert all(not any(r['summary']['ai_failures']) for r in result['matches'])
        assert all(not any(r['summary']['illegal_actions']) for r in result['matches'])
    payload={'utc':datetime.now(timezone.utc).isoformat(),'matches':91,'quick_matches':35,'balanced_matches':56,
             'wall_seconds':time.monotonic()-started,'bytes':sum(p.stat().st_size for p in out.rglob('*') if p.is_file()),
             'checks':['real SIGINT and preserved partial attempt','resume without duplicate matches','complete-block standings',
                       'real replay corruption rejected','frozen input mismatch rejected','2..8 quick blocks verified',
                       '8p exact ordered-pair block verified'],'ai_failures':0,'illegal_actions':0}
    (out/'acceptance.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(payload,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    main()
