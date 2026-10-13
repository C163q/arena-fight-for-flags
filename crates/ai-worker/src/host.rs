use crate::{
    protocol::{self, Request, Response},
    *,
};
use std::{
    io,
    os::{
        fd::{AsRawFd, RawFd},
        unix::{net::UnixStream, process::CommandExt},
    },
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    time::{Duration, Instant},
};
struct Process {
    child: Child,
    socket: UnixStream,
}
pub struct TeamHost {
    worker: PathBuf,
    library: PathBuf,
    init: CtfInit,
    process: Option<Process>,
    attempts: u32,
    request_id: u64,
}
fn signal(pid: u32, sig: i32) -> io::Result<()> {
    // SAFETY: pid is our own process-group leader; negative PID signals its group.
    if unsafe { libc::kill(-(pid as i32), sig) } == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}
impl Process {
    fn launch(worker: &Path, library: &Path, init: CtfInit) -> io::Result<Self> {
        let (parent, child_socket) = UnixStream::pair()?;
        let fd: RawFd = child_socket.as_raw_fd();
        let mut command = Command::new(worker);
        command
            .arg("--library")
            .arg(library)
            .arg("--fd")
            .arg(fd.to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .process_group(0);
        // SAFETY: only async-signal-safe libc syscalls run between fork and exec.
        unsafe {
            command.pre_exec(move || {
                let flags = libc::fcntl(fd, libc::F_GETFD);
                if flags < 0 || libc::fcntl(fd, libc::F_SETFD, flags & !libc::FD_CLOEXEC) < 0 {
                    return Err(io::Error::last_os_error());
                }
                let limit = libc::rlimit {
                    rlim_cur: 256 * 1024 * 1024,
                    rlim_max: 256 * 1024 * 1024,
                };
                if libc::setrlimit(libc::RLIMIT_AS, &limit) != 0 {
                    return Err(io::Error::last_os_error());
                }
                let core = libc::rlimit {
                    rlim_cur: 0,
                    rlim_max: 0,
                };
                if libc::setrlimit(libc::RLIMIT_CORE, &core) != 0 {
                    return Err(io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let child = command.spawn()?;
        drop(child_socket);
        let mut p = Self {
            child,
            socket: parent,
        };
        let deadline = Instant::now() + Duration::from_millis(1000);
        let ready = protocol::send(&mut p.socket, &Request::Init { init }, deadline)
            .and_then(|()| protocol::receive::<Response>(&mut p.socket, deadline));
        match ready {
            Ok(Response::Ready {
                abi_version: ABI_VERSION,
            }) => {
                p.stop()?;
                Ok(p)
            }
            Ok(Response::Error { message }) => Err(io::Error::other(message)),
            Ok(_) => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "unexpected initialization response",
            )),
            Err(e) => Err(e),
        }
    }
    fn stop(&mut self) -> io::Result<()> {
        signal(self.child.id(), libc::SIGSTOP)?;
        let deadline = Instant::now() + Duration::from_millis(200);
        loop {
            let mut status = 0;
            // SAFETY: waitpid observes only our direct child, status is writable.
            let result = unsafe {
                libc::waitpid(
                    self.child.id() as i32,
                    &mut status,
                    libc::WUNTRACED | libc::WNOHANG,
                )
            };
            if result < 0 {
                return Err(io::Error::last_os_error());
            }
            if result > 0 {
                return if libc::WIFSTOPPED(status) {
                    Ok(())
                } else {
                    Err(io::Error::other("worker exited while stopping"))
                };
            }
            if Instant::now() >= deadline {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "worker failed to stop",
                ));
            }
            std::thread::sleep(Duration::from_millis(1));
        }
    }
}
impl Drop for Process {
    fn drop(&mut self) {
        let _ = signal(self.child.id(), libc::SIGKILL);
        let _ = self.child.wait();
    }
}
impl TeamHost {
    pub fn new(worker: &Path, library: &Path, init: CtfInit) -> Self {
        Self {
            worker: worker.into(),
            library: library.into(),
            init,
            process: None,
            attempts: 0,
            request_id: 0,
        }
    }
    pub fn pid(&self) -> Option<u32> {
        self.process.as_ref().map(|p| p.child.id())
    }
    pub fn decide(&mut self, snapshot: &Snapshot, map: &MapDefinition) -> CallReport {
        let mut report = CallReport {
            team_id: self.init.team_id,
            turn: snapshot.turn,
            status: "ok".into(),
            elapsed_us: 0,
            init_elapsed_us: 0,
            restart_count: self.attempts.saturating_sub(1),
            actions: [Action::Wait; 3],
            raw_output: None,
            error: None,
        };
        if self.process.is_none() {
            let mut init = self.init;
            init.restart_count = self.attempts;
            init.first_turn = snapshot.turn;
            self.attempts += 1;
            report.restart_count = init.restart_count;
            let at = Instant::now();
            let result = Process::launch(&self.worker, &self.library, init);
            report.init_elapsed_us = at.elapsed().as_micros() as u64;
            match result {
                Ok(p) => self.process = Some(p),
                Err(e) => {
                    report.status = "load_error".into();
                    report.error = Some(e.to_string().chars().take(1000).collect());
                    return report;
                }
            }
        }
        let data = observation(snapshot, map, self.init.team_id);
        self.request_id += 1;
        let id = self.request_id;
        let p = self.process.as_mut().expect("initialized worker");
        let at = Instant::now();
        let deadline = at + Duration::from_millis(50);
        let response = signal(p.child.id(), libc::SIGCONT)
            .and_then(|()| {
                protocol::send(
                    &mut p.socket,
                    &Request::Decide {
                        request_id: id,
                        observation: data,
                    },
                    deadline,
                )
            })
            .and_then(|()| protocol::receive::<Response>(&mut p.socket, deadline));
        let status = match response {
            Ok(Response::Decision {
                request_id,
                status,
                output,
            }) if request_id == id => {
                report.raw_output = Some(output);
                if status != 0 {
                    Err(("ai_error", format!("AI returned {status}")))
                } else if !output.valid_layout() {
                    Err((
                        "protocol_error",
                        "invalid output version, size or slots".into(),
                    ))
                } else if Instant::now() > deadline {
                    Err(("timeout", "response validation exceeded deadline".into()))
                } else {
                    report.actions = output.actions.map(decode);
                    Ok(())
                }
            }
            Ok(_) => Err(("protocol_error", "unexpected/stale response".into())),
            Err(e) => Err((
                match e.kind() {
                    io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock => "timeout",
                    io::ErrorKind::InvalidData => "protocol_error",
                    _ => "crash",
                },
                e.to_string(),
            )),
        };
        report.elapsed_us = at.elapsed().as_micros() as u64;
        let status = status.and_then(|()| p.stop().map_err(|e| ("crash", e.to_string())));
        if let Err((kind, error)) = status {
            report.status = kind.into();
            report.error = Some(error.chars().take(1000).collect());
            report.actions = [Action::Wait; 3];
            self.process.take();
        }
        report
    }
}
impl Drop for TeamHost {
    fn drop(&mut self) {
        if let Some(mut p) = self.process.take() {
            let deadline = Instant::now() + Duration::from_millis(100);
            if signal(p.child.id(), libc::SIGCONT).is_ok() {
                let _ = protocol::send(&mut p.socket, &Request::Shutdown, deadline);
                let _ = protocol::receive::<Response>(&mut p.socket, deadline);
            }
        }
    }
}
