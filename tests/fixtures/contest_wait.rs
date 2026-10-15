// Test-only independent declarations written from the C header. Not shipped.
#![allow(dead_code)]
use core::ffi::c_void;
#[repr(C)] struct CtfInit {
    abi_version:u32,struct_size:u32,team_id:u32,team_count:u32,width:u32,height:u32,
    max_turns:u32,target_score:u32,flag_respawn_min_turns:u32,flag_respawn_max_turns:u32,
    first_turn:u32,restart_count:u32,seed:u64,decision_budget_us:u32,initial_flag_count:u32,
    max_hp:u32,shot_damage:u32,shot_range:u32,respawn_absent_turns:u32,
}
#[repr(C)] #[derive(Clone,Copy)] struct CtfAction {unit_id:u32,kind:u32,direction:u32,target_x:i32,target_y:i32}
#[repr(C)] struct CtfTeamAction {abi_version:u32,struct_size:u32,actions:[CtfAction;3]}
#[repr(C)] struct CtfUnit {team_id:u32,unit_id:u32,alive:u32,hp:u32,x:i32,y:i32,carrying:u32,respawn_at_turn:u32,flag_id:u64}
#[repr(C)] struct CtfFlag {id:u64,site_id:u32,state:u32,x:i32,y:i32,carrier_team:u32,carrier_unit:u32}
#[repr(C)] struct CtfHome {team_id:u32,x:i32,y:i32,width:u32,height:u32}
#[repr(C)] struct CtfSite {id:u32,x:i32,y:i32}
#[repr(C)] struct CtfObservation {
    abi_version:u32,struct_size:u32,turn:u32,team_id:u32,width:u32,height:u32,
    team_count:u32,unit_count:u32,flag_count:u32,site_count:u32,cell_count:u32,reserved:u32,
    cells:*const u8,units:*const CtfUnit,flags:*const CtfFlag,homes:*const CtfHome,sites:*const CtfSite,scores:*const u32,
}
const _: () = {
    assert!(size_of::<CtfInit>()==80 && align_of::<CtfInit>()==8);
    assert!(size_of::<CtfAction>()==20 && size_of::<CtfTeamAction>()==68);
    assert!(size_of::<CtfUnit>()==40 && size_of::<CtfFlag>()==32);
    assert!(size_of::<CtfHome>()==20 && size_of::<CtfSite>()==12);
    assert!(size_of::<CtfObservation>()==96 && core::mem::offset_of!(CtfObservation,cells)==48);
};
#[unsafe(no_mangle)] extern "C" fn ctf_abi_version()->u32 {1}
#[unsafe(no_mangle)] unsafe extern "C" fn ctf_create(init:*const CtfInit,out:*mut *mut c_void)->i32 {
    if init.is_null() || out.is_null() || unsafe{(*init).struct_size}!=80 {return 1;}
    unsafe{*out=core::ptr::null_mut();} 0
}
#[unsafe(no_mangle)] unsafe extern "C" fn ctf_decide(_ctx:*mut c_void,obs:*const CtfObservation,out:*mut CtfTeamAction)->i32 {
    if obs.is_null() || out.is_null() || unsafe{(*obs).struct_size}!=96 {return 1;}
    let mut actions=[CtfAction{unit_id:0,kind:0,direction:0,target_x:0,target_y:0};3];
    for (i,a) in actions.iter_mut().enumerate(){a.unit_id=i as u32;}
    unsafe{out.write(CtfTeamAction{abi_version:1,struct_size:68,actions});} 0
}
#[unsafe(no_mangle)] extern "C" fn ctf_destroy(_ctx:*mut c_void) {}
