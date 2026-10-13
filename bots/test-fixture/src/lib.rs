//! Failure injection library for isolated-process integration tests only.
use fff_ai_abi::*;
use std::ffi::c_void;
fn mode() -> String {
    std::env::var("FFF_TEST_MODE").unwrap_or_default()
}
#[unsafe(no_mangle)]
pub extern "C" fn ctf_abi_version() -> u32 {
    if mode() == "wrong_version" {
        999
    } else {
        ABI_VERSION
    }
}
/// # Safety
/// init and context_out are live worker-owned C ABI buffers.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn ctf_create(init: *const CtfInit, context_out: *mut *mut c_void) -> i32 {
    if mode() == "init_hang" {
        loop {
            std::hint::spin_loop();
        }
    }
    if init.is_null() || context_out.is_null() {
        return 1;
    }
    // SAFETY: non-null buffers are supplied by the worker.
    unsafe {
        *context_out = Box::into_raw(Box::new((*init).restart_count)) as *mut c_void;
    }
    0
}
/// # Safety
/// context originated from create; observation and output live for this call.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn ctf_decide(
    context: *mut c_void,
    _observation: *const CtfObservation,
    output: *mut CtfTeamAction,
) -> i32 {
    match mode().as_str() {
        "hang" => loop {
            std::hint::spin_loop();
        },
        "crash" => std::process::abort(),
        "first_hang" => {
            // SAFETY: context is our allocated u32.
            if unsafe { *(context as *const u32) } == 0 {
                loop {
                    std::hint::spin_loop();
                }
            }
        }
        "background" => {
            std::thread::spawn(|| {
                loop {
                    std::hint::spin_loop();
                }
            });
        }
        "error" => return 2,
        _ => {}
    }
    if output.is_null() {
        return 1;
    }
    let mut actions = CtfTeamAction::waits();
    if mode() == "partial" {
        actions.actions[2].unit_id = u32::MAX;
    }
    if mode() == "illegal_action" {
        actions.actions[0].kind = 999;
    }
    // SAFETY: output is writable worker memory.
    unsafe {
        *output = actions;
    }
    0
}
/// # Safety
/// context is the single Box returned by create and is destroyed at most once.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn ctf_destroy(context: *mut c_void) {
    if mode() == "destroy_hang" {
        loop {
            std::hint::spin_loop();
        }
    }
    if !context.is_null() {
        // SAFETY: context was created with Box::into_raw above.
        drop(unsafe { Box::from_raw(context as *mut u32) });
    }
}
