mod board;
mod forecast;
mod objectives;
mod search;

use board::{Board, NONE};
use fff_ai_abi::*;
use forecast::State;
use objectives::SiteMemory;
use std::{
    ffi::c_void,
    panic::{AssertUnwindSafe, catch_unwind},
};

struct Bot {
    board: Option<Board>,
    home: Vec<Vec<u16>>,
    team: usize,
    min_wait: u32,
    max_wait: u32,
    sites: Vec<SiteMemory>,
    last_pos: [usize; 3],
    last_goal: [usize; 3],
}
impl Bot {
    fn new(min_wait: u32, max_wait: u32) -> Self {
        Self {
            board: None,
            home: vec![],
            team: 0,
            min_wait,
            max_wait,
            sites: vec![],
            last_pos: [NONE; 3],
            last_goal: [NONE; 3],
        }
    }
    fn decide(&mut self, v: &ObservationView<'_>) -> CtfTeamAction {
        self.team = v.meta.team_id as usize;
        if self.board.is_none() {
            let b = Board::new(v.meta.width as usize, v.meta.height as usize, v.cells);
            self.home = vec![vec![]; v.meta.team_count as usize];
            for h in v.homes {
                let mut cells = vec![];
                for y in h.y..h.y + h.height as i32 {
                    for x in h.x..h.x + h.width as i32 {
                        if let Some(p) = b.cell(x, y) {
                            cells.push(p);
                        }
                    }
                }
                self.home[h.team_id as usize] = b.bfs(&cells);
            }
            self.board = Some(b);
        }
        let b = self.board.as_mut().unwrap();
        let mut s = State {
            pos: [NONE; 24],
            hp: [0; 24],
            carry: [false; 24],
            team: [0; 24],
            count: v.units.len(),
            ground: vec![0; b.n],
        };
        let mut mine = [NONE; 3];
        for (e, u) in v.units.iter().enumerate() {
            s.team[e] = u.team_id;
            if u.team_id == v.meta.team_id {
                mine[u.unit_id as usize] = e;
            }
            if u.alive != 0
                && let Some(p) = b.cell(u.x, u.y)
            {
                s.pos[e] = p;
                s.hp[e] = u.hp;
                s.carry[e] = u.carrying != 0;
                b.ensure(p);
            }
        }
        for f in v.flags.iter().filter(|f| f.state == 0) {
            if let Some(p) = b.cell(f.x, f.y) {
                s.ground[p] += 1;
                b.ensure(p);
            }
        }
        for site in v.sites {
            if let Some(p) = b.cell(site.x, site.y) {
                b.ensure(p);
            }
        }
        let goals = self.goals(v, &s);
        let assigned = self.assign(v, &s, &goals, &mine);
        self.search(v, &s, &goals, &mine, &assigned)
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn ctf_abi_version() -> u32 {
    ABI_VERSION
}

/// # Safety
/// The worker supplies live, aligned init/output buffers. Returned context belongs to this library.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn ctf_create(init: *const CtfInit, output: *mut *mut c_void) -> i32 {
    if output.is_null() {
        return 1;
    }
    // SAFETY: non-null output is writable by the ABI contract; failure returns no owned context.
    unsafe {
        *output = std::ptr::null_mut();
    }
    // SAFETY: worker guarantees a live aligned init, null is rejected by as_ref.
    let Some(init) = (unsafe { init.as_ref() }) else {
        return 1;
    };
    if !init.valid() {
        return 1;
    }
    match catch_unwind(AssertUnwindSafe(|| {
        Box::new(Bot::new(
            init.flag_respawn_min_turns,
            init.flag_respawn_max_turns,
        ))
    })) {
        Ok(context) => {
            unsafe {
                *output = Box::into_raw(context).cast();
            }
            0
        }
        Err(_) => 2,
    }
}
/// # Safety
/// Context must be returned by create; observation arrays/output live for the call. Calls are serial.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn ctf_decide(
    context: *mut c_void,
    observation: *const CtfObservation,
    output: *mut CtfTeamAction,
) -> i32 {
    if context.is_null() || output.is_null() {
        return 1;
    }
    // SAFETY: worker owns aligned buffers that outlive the returned view.
    let view = match unsafe { fff_ai_abi::view(observation) } {
        Ok(v) => v,
        Err(code) => return code,
    };
    match catch_unwind(AssertUnwindSafe(|| {
        // SAFETY: unique context from create, only accessed in serial worker calls.
        unsafe { &mut *context.cast::<Bot>() }.decide(&view)
    })) {
        Ok(actions) => {
            unsafe {
                *output = actions;
            }
            0
        }
        Err(_) => 2,
    }
}
/// # Safety
/// Context is null or a live context from create, and is destroyed exactly once.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn ctf_destroy(context: *mut c_void) {
    if !context.is_null() {
        // SAFETY: create allocated this Bot and the worker relinquishes its sole ownership.
        drop(unsafe { Box::from_raw(context.cast::<Bot>()) });
    }
}
#[cfg(test)]
mod tests;
