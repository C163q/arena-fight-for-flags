//! Deterministic syscall scheduling around the unchanged production state.rs.
//! No syscall return value is faked; all locks belong to real child processes.
use std::io::{BufRead, Read, Write};
use fff_session_timer::Error;

mod clock {
    pub fn now_ns() -> Result<u64, crate::Error> {
        unreachable!("this regression never publishes a timer origin")
    }
}

fn control(message: &str) {
    let mut socket = std::os::unix::net::UnixStream::connect(
        std::env::var("FFF_RACE_SOCKET").unwrap(),
    ).unwrap();
    socket.write_all(message.as_bytes()).unwrap();
    let mut response = [0];
    socket.read_exact(&mut response).unwrap();
}

mod libc {
    pub use raw_libc::*;
    static CALL: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

    pub unsafe fn fcntl<T>(fd: i32, cmd: i32, arg: *const T) -> i32 {
        if cmd == F_GETLK && unsafe { &*arg.cast::<flock>() }.l_start == 0 {
            let call = CALL.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            if call == 1 { super::control("start2"); }
            // SAFETY: production provides real valid flock storage; this test
            // delegates unchanged to the kernel and only schedules exits after.
            let result = unsafe { raw_libc::fcntl(fd, cmd, arg) };
            let observed = unsafe { &*arg.cast::<flock>() };
            assert_eq!(result, 0);
            assert_eq!(observed.l_pid, 0);
            assert_eq!(observed.l_type, F_WRLCK as i16);
            assert_eq!((observed.l_start, observed.l_len), (0, 2));
            eprintln!("real initialization snapshot {call}: pid=0 range=[0,2)");
            super::control(if call == 0 { "drop1" } else { "drop2" });
            return result;
        }
        // SAFETY: same pointer/command forwarded without alteration.
        unsafe { raw_libc::fcntl(fd, cmd, arg) }
    }
}

#[allow(dead_code)]
mod state {
    use crate::libc;
    include!(@STATE_SOURCE@);
}

fn main() {
    let path = std::env::var("FFF_RACE_STATE").unwrap();
    if std::env::args().nth(1).as_deref() == Some("hold") {
        let _session = state::Session::acquire(std::path::Path::new(&path)).unwrap();
        println!("LOCKED");
        std::io::stdout().flush().unwrap();
        let line = std::io::stdin().lock().lines().next().unwrap().unwrap();
        assert_eq!(line, "exit");
        return;
    }
    let result = state::query_record(std::path::Path::new(&path));
    println!("query with no published session: {result:?}");
    assert!(matches!(result, Err(Error::NotReady)), "accepted stale pre-query origin");
}
