"""Check that runner death cleans ordinary fork helpers, paused and active."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", type=Path, default=Path("target/debug"))
    args = parser.parse_args()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "subreaper")
    with tempfile.TemporaryDirectory(prefix="fff-parent-cleanup-") as scratch:
        root = Path(scratch)
        source = root / "fork.c"
        library = root / "fork.so"
        source.write_text(r'''
#include "ctf_ai.h"
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
uint32_t ctf_abi_version(void){return 1;}
int32_t ctf_create(const CtfInit *i,void **c){
 (void)i;*c=0;pid_t p=fork();if(p<0)return 2;
 if(p==0){for(;;){} }
 FILE *f=fopen(getenv("FFF_HELPER_PIDS"),"a");if(!f)return 2;
 fprintf(f,"%ld %ld\n",(long)getpid(),(long)p);fclose(f);return 0;
}
int32_t ctf_decide(void *c,const CtfObservation *o,CtfTeamAction *a){
 (void)c;(void)o;a->abi_version=1;a->struct_size=sizeof(*a);
 for(uint32_t i=0;i<3;i++)a->actions[i]=(CtfAction){.unit_id=i};return 0;
}
void ctf_destroy(void *c){(void)c;}
''')
        subprocess.run(["cc", "-shared", "-fPIC", "-O0", "-I", "include", str(source), "-o", str(library)], check=True)
        game_map = root / "map.ron"
        game_map.write_text(Path("maps/arena_2p.ron").read_text().replace("max_turns: 500", "max_turns: 1000000"))
        for mode in ("paused", "active"):
            pids_file = root / f"{mode}.pids"
            directory = root / mode
            command = [str(args.bin_dir / "fff-runner"), "--map", str(game_map), "--ai", str(library), "--ai", str(library), "--out", str(directory)]
            parent = subprocess.Popen(command, env=dict(os.environ, FFF_HELPER_PIDS=str(pids_file)), stdout=subprocess.DEVNULL)
            workers, descendants = [], set()
            try:
                deadline = time.monotonic() + 3
                while True:
                    pairs = [tuple(map(int, line.split())) for line in pids_file.read_text().splitlines()] if pids_file.exists() else []
                    workers = [worker for worker, _ in pairs]
                    descendants = {pid for pair in pairs for pid in pair}
                    frame = directory / "frames/000001.json"
                    if len(pairs) == 2 and frame.exists():
                        calls = json.loads(frame.read_text())["calls"]
                        assert all(call["status"] == "ok" for call in calls), calls
                        break
                    assert time.monotonic() < deadline, "fork fixture did not complete a frame"
                    time.sleep(.005)
                os.kill(parent.pid, signal.SIGSTOP)
                for worker in workers:
                    os.killpg(worker, signal.SIGSTOP if mode == "paused" else signal.SIGCONT)
                parent.kill()
                parent.wait(timeout=2)
                pending = set(descendants)
                deadline = time.monotonic() + 1
                while pending and time.monotonic() < deadline:
                    for pid in list(pending):
                        try:
                            found, _ = os.waitpid(pid, os.WNOHANG)
                            if found:
                                pending.remove(pid)
                        except ChildProcessError:
                            try:
                                os.kill(pid, 0)
                            except ProcessLookupError:
                                pending.remove(pid)
                    if pending:
                        time.sleep(.01)
                assert not pending, f"{mode}: live worker/helper survived runner death: {sorted(pending)}"
                print(f"PASS: {mode} workers and fork helpers exit on runner death", flush=True)
            finally:
                if parent.poll() is None:
                    parent.kill()
                    parent.wait()
                for worker in workers:
                    try:
                        os.killpg(worker, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                for pid in descendants:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                for _ in range(100):
                    try:
                        pid, _ = os.waitpid(-1, os.WNOHANG)
                        if pid == 0:
                            time.sleep(.005)
                    except ChildProcessError:
                        break

if __name__ == "__main__":
    main()
