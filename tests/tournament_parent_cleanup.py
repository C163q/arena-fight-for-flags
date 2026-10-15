"""SIGKILL the tournament parent during a real match, then resume safely."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from tournament_integration import REPO, CLI, invoke, load
sys.path.insert(0,str(REPO/'scripts'))
from tournament_lib.storage import locked


def live(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0] not in ('Z','X')
    except (FileNotFoundError,ProcessLookupError):
        return False


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--jobs',type=int,default=1,choices=[1,2])
    parser.add_argument('--bin-dir',type=Path,default=REPO/'target/release')
    args=parser.parse_args()
    out,bins=args.out.resolve(),args.bin_dir.resolve()
    if out.exists():
        parser.error('output must not exist')
    out.mkdir(parents=True)
    cfg={'version':1,'runner':str(bins/'fff-runner'),'mode':'quick','repeats':1,
         'ais':[{'id':f'bot{i}','library':str(bins/'libfff_bot_baseline.so')} for i in range(2)],
         'lineups':[{'id':'duel','players':2,'map':str(REPO/'maps/arena_2p.ron'),'ais':['bot0','bot1']}]}
    config=out/'config.json'
    config.write_text(json.dumps(cfg))
    root=out/'tournament'
    invoke('plan','--config',config,'--out',root)
    with (out/'kill.stdout.log').open('w') as stdout,(out/'kill.stderr.log').open('w') as stderr:
        parent=subprocess.Popen([sys.executable,str(CLI),'run',str(root),'--max-matches',str(args.jobs),'--jobs',str(args.jobs)],stdout=stdout,stderr=stderr)
        children=[]
        try:
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                manifests=list((root/'matches').glob('*/attempt-000/match/manifest.json'))
                if len(manifests)==args.jobs and all(load(p).get('status')=='in_progress' for p in manifests):
                    children=[]
                    for path in Path(f'/proc/{parent.pid}/task').glob('*/children'):
                        children.extend(int(p) for p in path.read_text().split())
                    if len(children)==args.jobs:
                        break
                if parent.poll() is not None:
                    raise AssertionError('match exited before SIGKILL test')
                time.sleep(.005)
            else:
                raise AssertionError('real runner not started')
            workers=[]
            for runner in children:
                workers.extend(int(p) for p in Path(f'/proc/{runner}/task/{runner}/children').read_text().split())
            parent.kill()
            parent.wait()
            try:
                with locked(root):
                    assert not any(live(p) for p in [*children,*workers]), 'output unlocked while orphan processes are live'
            except ValueError as error:
                assert 'locked' in str(error)
            deadline=time.monotonic()+5
            while any(live(p) for p in [*children,*workers]) and time.monotonic()<deadline:
                time.sleep(.005)
            assert not any(live(p) for p in [*children,*workers]), 'runner/worker survived SIGKILL'
            with locked(root):
                pass
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait()
    invoke('run',root)
    result=load(root/'results.json')
    assert result['completed_matches']==2
    assert result['groups'][0]['complete_blocks']==1
    assert len(list((root/'matches').glob('*/attempt-*')))==2+args.jobs
    assert all(not any(r['summary']['ai_failures']) and not any(r['summary']['illegal_actions']) for r in result['matches'])
    payload={'jobs':args.jobs,'killed_runners':len(children),'observed_workers':len(workers),'completed_matches':2,'sigkill_cleanup':True,'lock_covers_live_children':True,'resume_verified':True}
    (out/'acceptance.json').write_text(json.dumps(payload,indent=2)+'\n')
    print(json.dumps(payload),flush=True)


if __name__=='__main__':
    main()
