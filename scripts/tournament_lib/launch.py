"""Linux child guard: arm parent-death cleanup before exec without preexec_fn."""
import ctypes
import os
import signal
import sys


def main():
    expected_parent = int(sys.argv[1])
    command = sys.argv[2:]
    libc = ctypes.CDLL(None, use_errno=True)
    # Linux PR_SET_PDEATHSIG. This fresh, single-threaded helper avoids running
    # Python callbacks in the unsafe between-fork-and-exec phase of Popen.
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    if os.getppid() != expected_parent:
        # Parent may have died before prctl was armed; never start that match.
        os.kill(os.getpid(), signal.SIGKILL)
    os.execv(command[0], command)


if __name__ == '__main__':
    main()
