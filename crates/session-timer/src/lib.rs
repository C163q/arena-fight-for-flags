mod clock;
mod display;
mod state;

use std::{
    io::Write,
    path::Path,
    process::ExitCode,
    sync::atomic::{AtomicBool, Ordering},
    time::Duration,
};
const STATE_PATH: &str = "/tmp/fff-session-timer-v1";
static STOP: AtomicBool = AtomicBool::new(false);
#[derive(Debug)]
pub enum Error {
    NotRunning,
    AlreadyRunning,
    NotReady,
    InvalidState,
    Io(std::io::Error),
}
impl From<std::io::Error> for Error {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}
impl std::fmt::Display for Error {
    fn fmt(&self, output: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotRunning => write!(output, "计时器不存在（未运行）"),
            Self::AlreadyRunning => write!(output, "计时器已经运行，不能启动第二个实例"),
            Self::NotReady => write!(output, "计时器尚未就绪，请重试"),
            Self::InvalidState => write!(output, "计时器状态文件无效，未修改该文件"),
            Self::Io(error) => write!(output, "计时器系统错误：{error}"),
        }
    }
}
impl std::error::Error for Error {}
extern "C" fn stop_signal(_: libc::c_int) {
    STOP.store(true, Ordering::Relaxed);
}
fn install_signals() -> Result<(), Error> {
    for (signal, handler) in [
        (libc::SIGINT, stop_signal as *const () as usize),
        (libc::SIGTERM, stop_signal as *const () as usize),
        (libc::SIGHUP, libc::SIG_IGN),
        (libc::SIGPIPE, libc::SIG_IGN),
    ] {
        // SAFETY: all-zero sigaction is valid before initializing its mask and
        // handler; the handler only stores to a lock-free AtomicBool.
        let mut action: libc::sigaction = unsafe { std::mem::zeroed() };
        action.sa_sigaction = handler;
        // SAFETY: action/mask are valid storage. No pointers are retained; both
        // custom handlers have the C signal ABI and live for the process lifetime.
        if unsafe { libc::sigemptyset(&mut action.sa_mask) } != 0
            || unsafe { libc::sigaction(signal, &action, std::ptr::null_mut()) } != 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
    }
    Ok(())
}
fn timer() -> Result<(), Error> {
    install_signals()?;
    let mut session = state::Session::acquire(Path::new(STATE_PATH))?;
    session.publish()?;
    let mut terminal = display::Terminal::new();
    while !STOP.load(Ordering::Relaxed) {
        terminal.update(&clock::format_elapsed(
            session.record.start_ns,
            clock::now_ns()?,
        )?);
        std::thread::sleep(Duration::from_millis(100));
    }
    terminal.finish();
    Ok(())
}
fn query() -> Result<(), Error> {
    for attempt in 0..10 {
        match state::query_record(Path::new(STATE_PATH)) {
            Ok(record) => {
                let value = clock::format_elapsed(record.start_ns, clock::now_ns()?)?;
                std::io::stdout()
                    .lock()
                    .write_all(format!("{value}\n").as_bytes())?;
                return Ok(());
            }
            Err(Error::NotReady) if attempt < 9 => std::thread::sleep(Duration::from_millis(5)),
            Err(error) => return Err(error),
        }
    }
    Err(Error::NotReady)
}
fn entry(name: &str, run: fn() -> Result<(), Error>) -> ExitCode {
    if std::env::args_os().len() != 1 {
        eprintln!("用法：{name}（不接受参数）");
        return ExitCode::from(2);
    }
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            let code = if matches!(error, Error::NotRunning | Error::AlreadyRunning) {
                1
            } else {
                2
            };
            eprintln!("{error}");
            ExitCode::from(code)
        }
    }
}
pub fn timer_main() -> ExitCode {
    entry("fff-timer", timer)
}
pub fn query_main() -> ExitCode {
    entry("fff-timer-query", query)
}
