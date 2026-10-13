//! Parent-death cleanup that also runs when the worker group is SIGSTOPped.
use std::sync::atomic::{AtomicI32, Ordering};
static PARENT: AtomicI32 = AtomicI32::new(0);
static LEADER: AtomicI32 = AtomicI32::new(0);
extern "C" fn continued(_: libc::c_int) {
    let leader = LEADER.load(Ordering::Relaxed);
    // SAFETY: getpid/getppid/kill are async-signal-safe. Only the original group
    // leader handles cleanup; ordinary fork helpers inherit the handler but must
    // not kill the group when resumed by the live runner.
    unsafe {
        if libc::getpid() == leader && libc::getppid() != PARENT.load(Ordering::Relaxed) {
            libc::kill(-leader, libc::SIGKILL);
        }
    }
}
pub fn install(parent: libc::pid_t) -> Result<(), String> {
    // SAFETY: these syscalls only inspect this worker's process identity.
    let leader = unsafe { libc::getpid() };
    if unsafe { libc::getpgrp() } != leader {
        return Err("worker must lead its own process group".into());
    }
    PARENT.store(parent, Ordering::Relaxed);
    LEADER.store(leader, Ordering::Relaxed);
    // SAFETY: zero initialization is valid for sigaction, and its mask is then
    // initialized before registration. The handler uses no allocation or locks.
    let mut action: libc::sigaction = unsafe { std::mem::zeroed() };
    action.sa_sigaction = continued as *const () as usize;
    action.sa_flags = libc::SA_RESTART;
    unsafe {
        if libc::sigemptyset(&mut action.sa_mask) != 0
            || libc::sigaction(libc::SIGCONT, &action, std::ptr::null_mut()) != 0
        {
            return Err(std::io::Error::last_os_error().to_string());
        }
        if libc::getppid() != parent {
            return Err("runner exited before worker initialization".into());
        }
    }
    Ok(())
}
