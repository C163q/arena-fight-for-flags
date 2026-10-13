"""Real two-program, singleton, PTY and headless session-timer acceptance."""
import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import time

REPO=Path(__file__).resolve().parents[1]
STATE=Path('/tmp/fff-session-timer-v1')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir',type=Path,default=REPO/'target/release')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    bins,out=args.bin_dir.resolve(),args.out.resolve()
    timer,query=bins/'fff-timer',bins/'fff-timer-query'
    assert timer.is_file() and query.is_file(),'build fff-session-timer release binaries first'
    def ask():
        return subprocess.run([str(query)],capture_output=True,text=True,timeout=2)
    # Never signal a timer somebody else started.
    initial=ask()
    assert initial.returncode==1 and initial.stdout=='','an existing timer or state error prevents isolated acceptance'
    assert not out.exists(),'output must not exist'
    out.mkdir(parents=True)
    started=time.monotonic()
    checks=[]
    def value():
        result=ask()
        assert result.returncode==0,(result.returncode,result.stderr)
        assert re.fullmatch(r'\d{2}:\d{2}:\d{2}\n',result.stdout),repr(result.stdout)
        return result.stdout.strip()
    def ready(process):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            assert process.poll() is None,'timer exited during startup'
            result=ask()
            if result.returncode==0:
                assert int(STATE.read_text().split()[1])==process.pid,'not our timer'
                return value()
            time.sleep(.01)
        raise AssertionError('timer did not become ready')
    def stop(process,sig=signal.SIGTERM):
        process.send_signal(sig)
        code=process.wait(timeout=2)
        assert code==(0 if sig!=signal.SIGKILL else -signal.SIGKILL),code
        result=ask();assert result.returncode==1 and result.stdout==''
    def cleanup(process):
        if process.poll() is None:
            process.kill();process.wait()
    def seconds(text):
        h,m,s=map(int,text.split(':'));return h*3600+m*60+s
    quiet=subprocess.Popen([str(timer)],cwd='/tmp',stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        assert ready(quiet)=='00:00:00'
        before=STATE.read_bytes();meta=STATE.stat()
        duplicate=subprocess.run([str(timer)],cwd=str(REPO),capture_output=True,text=True,timeout=2)
        assert duplicate.returncode==1 and duplicate.stdout=='' and duplicate.stderr
        for bad in ([str(query),'--stop'],[str(query),'--path','/tmp/another-timer'],[str(timer),'--reset']):
            rejected=subprocess.run(bad,capture_output=True,text=True,timeout=2)
            assert rejected.returncode==2 and rejected.stdout==''
        # Independent query keeps advancing while timer has no event-loop CPU.
        quiet.send_signal(signal.SIGSTOP)
        before_time=seconds(value());time.sleep(1.15)
        assert seconds(value())>=before_time+1
        quiet.send_signal(signal.SIGCONT)
        assert STATE.read_bytes()==before and STATE.stat().st_mtime_ns==meta.st_mtime_ns
        assert meta.st_mode&0o777==0o666
        stop(quiet)
        stdout,stderr=quiet.communicate(timeout=2);assert stdout==stderr==b''
        checks += ['headless silence and advancing time','global singleton across cwd','control arguments rejected',
                   'query does not change record or locks','query independent of event loop']
    finally:
        cleanup(quiet)
    # Stale file must not restore a previous run, including after SIGKILL.
    for sig in (signal.SIGKILL,signal.SIGINT):
        process=subprocess.Popen([str(timer)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            assert ready(process)=='00:00:00'
            stop(process,sig)
            stdout,stderr=process.communicate(timeout=2);assert stdout==stderr==b''
        finally:cleanup(process)
    checks += ['SIGTERM/SIGINT/SIGKILL release singleton','restart starts at zero despite stale file']
    # Start competing processes together; only the selected PID may stay live.
    contenders=[subprocess.Popen([str(timer)],cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                for cwd in ('/tmp',str(REPO))]
    try:
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            result=ask()
            if result.returncode==0:
                winner_pid=int(STATE.read_text().split()[1])
                break
            time.sleep(.005)
        else:raise AssertionError('no contender became ready')
        winner=next((p for p in contenders if p.pid==winner_pid),None)
        assert winner is not None,'a timer outside this test acquired the singleton'
        loser=next(p for p in contenders if p is not winner)
        stdout,stderr=loser.communicate(timeout=2)
        assert loser.returncode==1 and stdout==b'' and stderr
        assert winner.poll() is None
        stop(winner)
        checks += ['simultaneous starts select exactly one winner']
    finally:
        for process in contenders:cleanup(process)
    def resize(fd,cols,rows):
        fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack('HHHH',rows,cols,0,0))
    def receive(fd,period=.45):
        result=b'';deadline=time.monotonic()+period
        while time.monotonic()<deadline:
            readable,_,_=select.select([fd],[],[],max(0,deadline-time.monotonic()))
            if not readable:break
            try:
                data=os.read(fd,65536)
                if not data:break
                result+=data
            except OSError as error:
                if error.errno==errno.EIO:break
                raise
        return result
    master,slave=pty.openpty();resize(slave,80,24)
    flags=fcntl.fcntl(slave,fcntl.F_GETFL)
    process=subprocess.Popen([str(timer)],stdout=slave,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL,env={**os.environ,'TERM':'xterm-256color'})
    try:
        ready(process);large=receive(master)
        assert '█'.encode() in large and b'\x1b[?1049h' in large
        (out/'large-80x24.ansi').write_bytes(large)
        assert fcntl.fcntl(slave,fcntl.F_GETFL)==flags,'timer changed parent stdout flags'
        resize(slave,20,4);small=receive(master)
        assert b'\x1b[2J' in small and '█'.encode() not in small and re.search(rb'\d{2}:\d{2}:\d{2}',small)
        resize(slave,160,40);wide=receive(master)
        assert wide.count('█'.encode())>large.count('█'.encode())
        (out/'wide-160x40.ansi').write_bytes(wide)
        process.send_signal(signal.SIGINT);assert process.wait(timeout=2)==0
        tail=receive(master,.1);assert b'\x1b[?1049l' in tail and b'\x1b[?25h' in tail
        checks += ['large glyphs and live resize fallback/scaling','output flags preserved','normal terminal restoration']
    finally:
        cleanup(process);os.close(master);os.close(slave)
    # Closing a display must not stop timing.
    master,slave=pty.openpty();resize(slave,80,24)
    process=subprocess.Popen([str(timer)],stdout=slave,stderr=subprocess.PIPE,env={**os.environ,'TERM':'xterm'})
    try:
        ready(process);receive(master,.1);os.close(master);master=-1
        time.sleep(.3);assert process.poll() is None;value();stop(process)
        assert process.stderr.read()==b''
        checks += ['closed display keeps counting']
    finally:
        cleanup(process)
        if master>=0:os.close(master)
        os.close(slave)
    # Deliberately fill a large PTY without reading. SIGTERM still must finish.
    master,slave=pty.openpty();resize(slave,2000,1000)
    process=subprocess.Popen([str(timer)],stdout=slave,stderr=subprocess.PIPE,env={**os.environ,'TERM':'xterm'})
    try:
        ready(process);time.sleep(.3);value();stop(process)
        checks += ['backpressured display cannot block exit']
    finally:cleanup(process);os.close(master);os.close(slave)
    master,slave=pty.openpty();resize(slave,160,40)
    process=subprocess.Popen([str(timer)],stdout=slave,stderr=subprocess.PIPE,env={**os.environ,'TERM':'dumb'})
    try:
        ready(process);plain=receive(master)
        assert re.search(rb'\d{2}:\d{2}:\d{2}',plain) and b'\x1b' not in plain and '█'.encode() not in plain
        stop(process);checks += ['dumb terminal uses basic time without ANSI']
    finally:cleanup(process);os.close(master);os.close(slave)
    assert ask().returncode==1
    result={'checks':checks,'wall_seconds':time.monotonic()-started,'no_timer_left_running':True}
    (out/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
