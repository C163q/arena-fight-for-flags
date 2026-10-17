"""Kill a selftest controller with two real runners; verify inner-lock cleanup."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from selftest_integration import REPO,CLI,invoke,short_map,load
from tournament_parent_cleanup import live
sys.path.insert(0,str(REPO/'scripts'))
from contest_lib.experiment import prepare_suite,locked_suite
from contest_lib.archive import archive_records

def descendants(pid):
    result=[]
    for task in Path(f'/proc/{pid}/task').glob('*/children'):
        try:result.extend(int(p) for p in task.read_text().split())
        except FileNotFoundError:pass
    return list(set(result))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--bin-dir',type=Path,default=REPO/'target/release')
    args=parser.parse_args();out=args.out.resolve();bins=args.bin_dir.resolve()
    if out.exists():parser.error('output must not exist')
    out.mkdir(parents=True)
    # Test-only deliberate CPU delay; enough time to observe every worker, below budget.
    source=out/'slow.c'
    source.write_text('#define _POSIX_C_SOURCE 200809L\n#include <time.h>\n'+
        (REPO/'tests/fixtures/contest_wait.c').read_text().replace(
        '(void)ctx;', '(void)ctx; struct timespec delay={0,20000000}; nanosleep(&delay,NULL);'))
    library=out/'slow.so'
    subprocess.run(['cc','-std=c11','-O2','-shared','-fPIC','-I'+str(REPO/'include'),str(source),'-o',str(library)],check=True)
    root=out/'suite';runner=bins/'fff-runner'
    prepare_suite([('candidate',library)],[short_map(out/'map.ron',12)],library,runner,root)
    with (out/'parent.stdout').open('w') as stdout,(out/'parent.stderr').open('w') as stderr:
        parent=subprocess.Popen([sys.executable,str(CLI),'resume',str(root),'--jobs','2'],stdout=stdout,stderr=stderr)
        runners=[];workers=[]
        try:
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                runners=descendants(parent.pid);workers=[w for r in runners for w in descendants(r)]
                if len(runners)==2 and len(workers)>=4:break
                assert parent.poll() is None,'controller exited before observation'
                time.sleep(.005)
            else:raise AssertionError('two runners and four workers not observed')
            # Both operations must refuse while inner runners are active.
            try:
                with locked_suite(root):raise AssertionError('active suite unexpectedly unlocked')
            except ValueError as error:assert 'locked' in str(error)
            try:archive_records(root,out/'active.tar.gz',runner)
            except ValueError as error:assert 'locked' in str(error)
            else:raise AssertionError('active archive accepted')
            parent.kill();parent.wait(timeout=5)
            try:
                with locked_suite(root):assert not any(live(p) for p in runners+workers),'locks released before child cleanup'
            except ValueError as error:assert 'locked' in str(error)
            deadline=time.monotonic()+5
            while any(live(p) for p in runners+workers) and time.monotonic()<deadline:time.sleep(.005)
            assert not any(live(p) for p in runners+workers),'orphan process remains'
            with locked_suite(root):pass
        finally:
            if parent.poll() is None:parent.kill();parent.wait()
    invoke('resume',root)
    result=load(root/'results.json');assert result['completed_matches']==2
    assert len(list(root.glob('versions/*/matches/*/attempt-*')))==4
    payload={'passed':True,'jobs':2,'killed_runners':len(runners),'observed_workers':len(workers),
             'all_children_cleaned':True,'active_operations_refused':True,'inner_locks_cover_cleanup':True,'resumed_games':2}
    (out/'acceptance.json').write_text(json.dumps(payload,indent=2)+'\n');print(json.dumps(payload),flush=True)

if __name__=='__main__':main()
