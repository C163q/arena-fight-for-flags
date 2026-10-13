use fff_ai_abi::*;
use fff_ai_worker::protocol::{self, Request, Response};
use libloading::Library;
use std::{
    ffi::c_void,
    os::{
        fd::{FromRawFd, RawFd},
        unix::net::UnixStream,
    },
    path::PathBuf,
    time::{Duration, Instant},
};
fn respond(socket: &mut UnixStream, message: &Response) -> std::io::Result<()> {
    protocol::send(socket, message, Instant::now() + Duration::from_secs(2))
}
fn run() -> Result<(), String> {
    // SAFETY: affects only this worker; suppress system core handlers on AI crashes.
    if unsafe { libc::prctl(libc::PR_SET_DUMPABLE, 0, 0, 0, 0) } != 0 {
        return Err(std::io::Error::last_os_error().to_string());
    }
    let mut args = std::env::args_os().skip(1);
    let mut path = None;
    let mut fd = None;
    while let Some(arg) = args.next() {
        if arg == "--library" {
            path = args.next().map(PathBuf::from);
        } else if arg == "--fd" {
            fd = args
                .next()
                .and_then(|s| s.to_str().and_then(|s| s.parse::<RawFd>().ok()));
        } else {
            return Err("unknown worker argument".into());
        }
    }
    let path = path.ok_or("missing library")?;
    let fd = fd.filter(|&fd| fd > 2).ok_or("missing inherited socket")?;
    // SAFETY: the parent transfers this inherited descriptor solely to this worker.
    let mut socket = unsafe { UnixStream::from_raw_fd(fd) };
    let Request::Init { init } =
        protocol::receive(&mut socket, Instant::now() + Duration::from_secs(2))
            .map_err(|e| e.to_string())?
    else {
        return Err("expected init".into());
    };
    let loaded = (|| -> Result<_, String> {
        if !init.valid() {
            return Err("invalid initialization".into());
        }
        // SAFETY: native AI is intentionally loaded only in this isolated process.
        let library = unsafe { Library::new(&path) }.map_err(|e| e.to_string())?;
        // SAFETY: exported v1 symbols use the documented C signatures; the library
        // remains alive until after destroy. ABI mismatch or crashes stay here.
        let (version, create, decide, destroy) = unsafe {
            (
                *library
                    .get::<VersionFn>(b"ctf_abi_version\0")
                    .map_err(|e| e.to_string())?,
                *library
                    .get::<CreateFn>(b"ctf_create\0")
                    .map_err(|e| e.to_string())?,
                *library
                    .get::<DecideFn>(b"ctf_decide\0")
                    .map_err(|e| e.to_string())?,
                *library
                    .get::<DestroyFn>(b"ctf_destroy\0")
                    .map_err(|e| e.to_string())?,
            )
        };
        // SAFETY: version takes no pointers; function is from the live library.
        if unsafe { version() } != ABI_VERSION {
            return Err("unsupported AI ABI version".into());
        }
        let mut context: *mut c_void = std::ptr::null_mut();
        // SAFETY: init and context output remain live throughout this call.
        if unsafe { create(&init, &mut context) } != 0 {
            return Err("AI initialization failed".into());
        }
        Ok((library, decide, destroy, context))
    })();
    let (library, decide, destroy, context) = match loaded {
        Ok(v) => v,
        Err(message) => {
            respond(&mut socket, &Response::Error { message }).map_err(|e| e.to_string())?;
            return Ok(());
        }
    };
    respond(
        &mut socket,
        &Response::Ready {
            abi_version: ABI_VERSION,
        },
    )
    .map_err(|e| e.to_string())?;
    loop {
        let request = protocol::receive(
            &mut socket,
            Instant::now() + Duration::from_secs(315_360_000),
        )
        .map_err(|e| e.to_string())?;
        match request {
            Request::Decide {
                request_id,
                observation,
            } => {
                let borrowed = observation.borrowed();
                let mut output = CtfTeamAction::unwritten();
                // SAFETY: all borrowed pointers refer to observation vectors held
                // across the call; writable output is correctly aligned and sized.
                let status = unsafe { decide(context, &borrowed, &mut output) };
                respond(
                    &mut socket,
                    &Response::Decision {
                        request_id,
                        status,
                        output,
                    },
                )
                .map_err(|e| e.to_string())?;
            }
            Request::Shutdown => {
                // SAFETY: context is exactly the value produced by this library.
                unsafe { destroy(context) };
                respond(&mut socket, &Response::Bye).map_err(|e| e.to_string())?;
                break;
            }
            _ => return Err("duplicate initialization".into()),
        }
    }
    drop(library);
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("worker: {error}");
        std::process::exit(1);
    }
}
