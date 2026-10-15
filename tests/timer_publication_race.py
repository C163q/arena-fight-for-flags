"""Require real PID isolation and reject stale state during failed initializers.

Only private temporary state files are used; never starts the real timer.
"""
import json
import os
from pathlib import Path
import re
import select
import socket
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    # Require the namespace instead of silently passing an unexercised test.
    subprocess.run(['unshare', '--user', '--map-root-user', '--pid', '--fork', '--mount-proc', 'true'], check=True)
    with tempfile.TemporaryDirectory(prefix='fff-timer-race-') as directory:
        root = Path(directory)
        (root / 'src').mkdir()
        version = re.search(r'libc\s*=\s*"([^"]+)"', (ROOT / 'Cargo.toml').read_text())[1]
        (root / 'Cargo.toml').write_text(
            '[package]\nname="fff-timer-publication-race"\nversion="0.0.0"\nedition="2024"\n'
            '[dependencies]\nraw_libc={package="libc",version=' + json.dumps(version) + '}\n'
            'fff-session-timer={path=' + json.dumps(str(ROOT / 'crates/session-timer')) + '}\n')
        source = (ROOT / 'tests/fixtures/timer_publication_race.rs').read_text()
        source = source.replace('@STATE_SOURCE@', json.dumps(str(ROOT / 'crates/session-timer/src/state.rs')))
        (root / 'src/main.rs').write_text(source)
        environment = {**os.environ, 'CARGO_TARGET_DIR': str(root / 'target')}
        subprocess.run(['cargo', 'build', '--offline', '--quiet', '--manifest-path', str(root / 'Cargo.toml')],
                       env=environment, check=True, timeout=60)
        binary = root / 'target/debug/fff-timer-publication-race'
        state = root / 'state'
        stale = 'FFF_TIMER_V1 123456 1\n'
        state.write_text(stale)
        environment.update(FFF_RACE_STATE=str(state), FFF_RACE_SOCKET=str(root / 'control'))
        holders = []

        def start():
            child = subprocess.Popen([str(binary), 'hold'], env=environment,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            holders.append(child)
            deadline = time.monotonic() + 3
            data = b''
            while b'LOCKED\n' not in data:
                assert child.poll() is None and time.monotonic() < deadline, 'holder did not initialize'
                readable, _, _ = select.select([child.stdout], [], [], .1)
                if readable:
                    chunk = os.read(child.stdout.fileno(), 4096)
                    assert chunk, 'holder exited before locking'
                    data += chunk

        def stop():
            child = holders[-1]
            child.stdin.write(b'exit\n')
            child.stdin.flush()
            assert child.wait(timeout=3) == 0

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(root / 'control'))
            server.listen()
            server.settimeout(.05)
            client = None
            try:
                start()
                client = subprocess.Popen(['unshare', '--user', '--map-root-user', '--pid', '--fork',
                                           '--mount-proc', '--kill-child=KILL', str(binary)],
                                          env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                messages = []
                deadline = time.monotonic() + 5
                while client.poll() is None:
                    assert time.monotonic() < deadline, 'race query hung'
                    try:
                        connection, _ = server.accept()
                    except socket.timeout:
                        continue
                    with connection:
                        connection.settimeout(2)
                        message = connection.recv(32).decode()
                        assert message == ('drop1', 'start2', 'drop2')[len(messages)], message
                        messages.append(message)
                        if message == 'start2':
                            start()
                        else:
                            stop()
                        connection.sendall(b'1')
                stdout, stderr = client.communicate(timeout=2)
                assert client.returncode == 0, (stdout.decode(), stderr.decode())
                assert messages == ['drop1'], messages  # reject the first atomic init snapshot
                assert state.read_text() == stale
                print('PASS: real invisible-PID initialization race rejects stale origin; no published session')
            finally:
                if client is not None and client.poll() is None:
                    client.kill()
                    client.wait()
                for child in holders:
                    if child.poll() is None:
                        child.kill()
                    child.wait()


if __name__ == '__main__':
    main()
