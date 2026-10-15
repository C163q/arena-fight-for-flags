use serde::{Deserialize, Serialize};
use std::ffi::c_void;
pub const ABI_VERSION: u32 = 1;
pub const TEAM_SIZE: usize = 3;
pub const MAX_HP: u32 = 3;
pub const SHOT_DAMAGE: u32 = 1;
pub const SHOT_RANGE: u32 = 5;
pub const WAIT: u32 = 0;
pub const MOVE: u32 = 1;
pub const SHOOT: u32 = 2;
pub const UP: u32 = 0;
pub const DOWN: u32 = 1;
pub const LEFT: u32 = 2;
pub const RIGHT: u32 = 3;
#[repr(C)]
#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
pub struct CtfInit {
    pub abi_version: u32,
    pub struct_size: u32,
    pub team_id: u32,
    pub team_count: u32,
    pub width: u32,
    pub height: u32,
    pub max_turns: u32,
    pub target_score: u32,
    pub flag_respawn_min_turns: u32,
    pub flag_respawn_max_turns: u32,
    pub first_turn: u32,
    pub restart_count: u32,
    pub seed: u64,
    /// Regular-turn budget. Match observation turn 1 allows 250000us;
    /// worker restarts do not grant another first-turn allowance.
    pub decision_budget_us: u32,
    pub initial_flag_count: u32,
    pub max_hp: u32,
    pub shot_damage: u32,
    pub shot_range: u32,
    pub respawn_absent_turns: u32,
}
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct CtfAction {
    pub unit_id: u32,
    pub kind: u32,
    pub direction: u32,
    pub target_x: i32,
    pub target_y: i32,
}
#[repr(C)]
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct CtfTeamAction {
    pub abi_version: u32,
    pub struct_size: u32,
    pub actions: [CtfAction; 3],
}
impl CtfTeamAction {
    pub fn waits() -> Self {
        Self {
            abi_version: ABI_VERSION,
            struct_size: std::mem::size_of::<Self>() as u32,
            actions: std::array::from_fn(|i| CtfAction {
                unit_id: i as u32,
                ..CtfAction::default()
            }),
        }
    }
    pub fn unwritten() -> Self {
        Self {
            abi_version: 0,
            struct_size: 0,
            actions: [CtfAction {
                unit_id: u32::MAX,
                ..CtfAction::default()
            }; 3],
        }
    }
    pub fn valid_layout(&self) -> bool {
        self.abi_version == ABI_VERSION
            && self.struct_size == std::mem::size_of::<Self>() as u32
            && self
                .actions
                .iter()
                .enumerate()
                .all(|(i, a)| a.unit_id == i as u32)
    }
}
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
pub struct CtfUnit {
    pub team_id: u32,
    pub unit_id: u32,
    pub alive: u32,
    pub hp: u32,
    pub x: i32,
    pub y: i32,
    pub carrying: u32,
    pub respawn_at_turn: u32,
    pub flag_id: u64,
}
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
pub struct CtfFlag {
    pub id: u64,
    pub site_id: u32,
    pub state: u32,
    pub x: i32,
    pub y: i32,
    pub carrier_team: u32,
    pub carrier_unit: u32,
}
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
pub struct CtfHome {
    pub team_id: u32,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
pub struct CtfSite {
    pub id: u32,
    pub x: i32,
    pub y: i32,
}
#[repr(C)]
pub struct CtfObservation {
    pub abi_version: u32,
    pub struct_size: u32,
    pub turn: u32,
    pub team_id: u32,
    pub width: u32,
    pub height: u32,
    pub team_count: u32,
    pub unit_count: u32,
    pub flag_count: u32,
    pub site_count: u32,
    pub cell_count: u32,
    pub reserved: u32,
    pub cells: *const u8,
    pub units: *const CtfUnit,
    pub flags: *const CtfFlag,
    pub homes: *const CtfHome,
    pub sites: *const CtfSite,
    pub scores: *const u32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ObservationData {
    pub turn: u32,
    pub team_id: u32,
    pub width: u32,
    pub height: u32,
    pub cells: Vec<u8>,
    pub units: Vec<CtfUnit>,
    pub flags: Vec<CtfFlag>,
    pub homes: Vec<CtfHome>,
    pub sites: Vec<CtfSite>,
    pub scores: Vec<u32>,
}
impl ObservationData {
    pub fn borrowed(&self) -> CtfObservation {
        CtfObservation {
            abi_version: ABI_VERSION,
            struct_size: std::mem::size_of::<CtfObservation>() as u32,
            turn: self.turn,
            team_id: self.team_id,
            width: self.width,
            height: self.height,
            team_count: self.scores.len() as u32,
            unit_count: self.units.len() as u32,
            flag_count: self.flags.len() as u32,
            site_count: self.sites.len() as u32,
            cell_count: self.cells.len() as u32,
            reserved: 0,
            cells: self.cells.as_ptr(),
            units: self.units.as_ptr(),
            flags: self.flags.as_ptr(),
            homes: self.homes.as_ptr(),
            sites: self.sites.as_ptr(),
            scores: self.scores.as_ptr(),
        }
    }
}
pub struct ObservationView<'a> {
    pub meta: &'a CtfObservation,
    pub cells: &'a [u8],
    pub units: &'a [CtfUnit],
    pub flags: &'a [CtfFlag],
    pub homes: &'a [CtfHome],
    pub sites: &'a [CtfSite],
    pub scores: &'a [u32],
}
/// # Safety
/// The non-null pointer and all advertised arrays must point to valid, aligned
/// buffers that remain alive for the returned borrow. Called inside the worker.
pub unsafe fn view<'a>(raw: *const CtfObservation) -> Result<ObservationView<'a>, i32> {
    // SAFETY: caller supplies a live CtfObservation; null is explicitly rejected.
    let m = unsafe { raw.as_ref() }.ok_or(1)?;
    if m.abi_version != ABI_VERSION
        || m.struct_size != std::mem::size_of::<CtfObservation>() as u32
        || !(2..=8).contains(&m.team_count)
        || m.team_id >= m.team_count
        || !(9..=128).contains(&m.width)
        || !(9..=128).contains(&m.height)
        || m.cell_count != m.width * m.height
        || m.unit_count != m.team_count * 3
        || m.flag_count > 32
        || m.site_count == 0
        || m.site_count > 32
    {
        return Err(1);
    }
    unsafe fn borrow<'a, T>(ptr: *const T, len: u32) -> Result<&'a [T], i32> {
        if len == 0 {
            return Ok(&[]);
        }
        if ptr.is_null() || !(ptr as usize).is_multiple_of(std::mem::align_of::<T>()) {
            return Err(1);
        }
        // SAFETY: array validity and lifetime are part of view's caller contract.
        Ok(unsafe { std::slice::from_raw_parts(ptr, len as usize) })
    }
    // SAFETY: lengths were bounded above and the caller owns all live arrays.
    unsafe {
        Ok(ObservationView {
            meta: m,
            cells: borrow(m.cells, m.cell_count)?,
            units: borrow(m.units, m.unit_count)?,
            flags: borrow(m.flags, m.flag_count)?,
            homes: borrow(m.homes, m.team_count)?,
            sites: borrow(m.sites, m.site_count)?,
            scores: borrow(m.scores, m.team_count)?,
        })
    }
}
pub type VersionFn = unsafe extern "C" fn() -> u32;
pub type CreateFn = unsafe extern "C" fn(*const CtfInit, *mut *mut c_void) -> i32;
pub type DecideFn =
    unsafe extern "C" fn(*mut c_void, *const CtfObservation, *mut CtfTeamAction) -> i32;
pub type DestroyFn = unsafe extern "C" fn(*mut c_void);

impl CtfInit {
    pub fn valid(&self) -> bool {
        self.abi_version == ABI_VERSION
            && self.struct_size == std::mem::size_of::<Self>() as u32
            && self.team_count >= 2
            && self.team_count <= 8
            && self.team_id < self.team_count
            && self.width >= 9
            && self.width <= 128
            && self.height >= 9
            && self.height <= 128
            && self.flag_respawn_min_turns > 0
            && self.flag_respawn_min_turns <= self.flag_respawn_max_turns
    }
}
/// Export a stateless Rust strategy through the complete v1 C lifecycle.
#[macro_export]
macro_rules! export_ai {
    ($strategy:path) => {
        #[unsafe(no_mangle)]
        pub extern "C" fn ctf_abi_version() -> u32 {
            $crate::ABI_VERSION
        }
        /// # Safety
        /// init and context_out must be valid pointers to their advertised types.
        #[unsafe(no_mangle)]
        pub unsafe extern "C" fn ctf_create(
            init: *const $crate::CtfInit,
            context_out: *mut *mut std::ffi::c_void,
        ) -> i32 {
            if init.is_null() || context_out.is_null() {
                return 1;
            }
            // SAFETY: the worker supplies initialized, properly aligned buffers.
            if !unsafe { &*init }.valid() {
                return 1;
            }
            // SAFETY: checked non-null output owned by caller; no context allocation.
            unsafe {
                *context_out = std::ptr::null_mut();
            }
            0
        }
        /// # Safety
        /// observation and its arrays must remain live for the call; output is writable.
        #[unsafe(no_mangle)]
        pub unsafe extern "C" fn ctf_decide(
            _context: *mut std::ffi::c_void,
            observation: *const $crate::CtfObservation,
            output: *mut $crate::CtfTeamAction,
        ) -> i32 {
            if output.is_null() {
                return 1;
            }
            // SAFETY: worker guarantees observation buffers and call duration.
            let view = match unsafe { $crate::view(observation) } {
                Ok(v) => v,
                Err(code) => return code,
            };
            match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| $strategy(&view))) {
                Ok(actions) => {
                    // SAFETY: output is writable for this call.
                    unsafe {
                        *output = actions;
                    }
                    0
                }
                Err(_) => 2,
            }
        }
        /// # Safety
        /// context must be a value returned by this library's create function.
        #[unsafe(no_mangle)]
        pub unsafe extern "C" fn ctf_destroy(_context: *mut std::ffi::c_void) {}
    };
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn output_has_three_ordered_slots_and_rejects_partial_writes() {
        let mut output = CtfTeamAction::waits();
        assert!(output.valid_layout());
        assert_eq!(output.actions.map(|a| a.unit_id), [0, 1, 2]);
        assert!(output.actions.iter().all(|a| a.kind == WAIT));
        output.actions[2].unit_id = u32::MAX;
        assert!(!output.valid_layout());
        assert!(!CtfTeamAction::unwritten().valid_layout());
    }
    #[test]
    fn null_observation_is_rejected_before_dereference() {
        assert!(unsafe { view(std::ptr::null()) }.is_err());
    }
    #[test]
    fn c_header_layout_and_symbols_match_rust_contract() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let dir = std::env::temp_dir().join(format!("fff-abi-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let source = dir.join("layout.c");
        let output = dir.join("layout");
        std::fs::write(&source,format!("#include <stddef.h>\n#include \"ctf_ai.h\"\n_Static_assert(sizeof(CtfInit)=={},\"init\");\n_Static_assert(sizeof(CtfTeamAction)=={},\"action\");\n_Static_assert(sizeof(CtfUnit)=={},\"unit\");\n_Static_assert(sizeof(CtfObservation)=={},\"observation\");\n_Static_assert(offsetof(CtfObservation,cells)=={},\"cells offset\");\nint main(void){{return CTF_ABI_VERSION!=1;}}\n",std::mem::size_of::<CtfInit>(),std::mem::size_of::<CtfTeamAction>(),std::mem::size_of::<CtfUnit>(),std::mem::size_of::<CtfObservation>(),std::mem::offset_of!(CtfObservation,cells))).unwrap();
        assert!(
            std::process::Command::new("cc")
                .arg("-std=c11")
                .arg("-Wall")
                .arg("-Werror")
                .arg("-I")
                .arg(root.join("include"))
                .arg(&source)
                .arg("-o")
                .arg(&output)
                .status()
                .unwrap()
                .success()
        );
        assert!(
            std::process::Command::new(output)
                .status()
                .unwrap()
                .success()
        );
        std::fs::remove_dir_all(dir).unwrap();
    }
}
