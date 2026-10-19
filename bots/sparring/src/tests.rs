use super::*;
fn fixture() -> ObservationData {
    let w = 15;
    let mut cells = vec![0; 225];
    for y in 0..w {
        for x in 0..w {
            if x == 0 || y == 0 || x == w - 1 || y == w - 1 {
                cells[y * w + x] = 1;
            }
        }
    }
    ObservationData {
        turn: 1,
        team_id: 0,
        width: 15,
        height: 15,
        cells,
        units: (0..6)
            .map(|i| CtfUnit {
                team_id: i / 3,
                unit_id: i % 3,
                ..CtfUnit::default()
            })
            .collect(),
        flags: vec![],
        homes: vec![
            CtfHome {
                team_id: 0,
                x: 1,
                y: 1,
                width: 3,
                height: 3,
            },
            CtfHome {
                team_id: 1,
                x: 11,
                y: 11,
                width: 3,
                height: 3,
            },
        ],
        sites: vec![CtfSite { id: 7, x: 7, y: 7 }],
        scores: vec![0, 0],
    }
}
fn put(o: &mut ObservationData, v: usize, x: i32, y: i32, hp: u32, carry: bool) {
    o.units[v].alive = 1;
    o.units[v].hp = hp;
    o.units[v].x = x;
    o.units[v].y = y;
    o.units[v].carrying = carry as u32;
}
fn choose(o: &ObservationData) -> CtfTeamAction {
    let raw = o.borrowed();
    let v = unsafe { fff_ai_abi::view(&raw) }.unwrap();
    Bot::new(5, 15).decide(&v)
}
#[test]
fn lone_carrier_returns_to_any_home_cell() {
    let mut o = fixture();
    put(&mut o, 0, 4, 2, 3, true);
    let a = choose(&o);
    assert_eq!(a.actions[0].kind, MOVE);
    assert_eq!(a.actions[0].direction, LEFT);
}
#[test]
fn available_flag_is_collected_instead_of_waiting() {
    let mut o = fixture();
    put(&mut o, 0, 6, 7, 3, false);
    o.flags.push(CtfFlag {
        id: 3,
        site_id: 7,
        x: 7,
        y: 7,
        ..CtfFlag::default()
    });
    let a = choose(&o);
    assert_eq!((a.actions[0].kind, a.actions[0].direction), (MOVE, RIGHT));
}
#[test]
fn joint_shots_finish_a_three_health_target() {
    let mut o = fixture();
    put(&mut o, 0, 5, 5, 3, false);
    put(&mut o, 1, 6, 4, 3, false);
    put(&mut o, 2, 6, 6, 3, false);
    put(&mut o, 3, 7, 5, 3, true);
    let a = choose(&o);
    assert!(
        a.actions
            .iter()
            .all(|a| a.kind == SHOOT && a.target_x == 7 && a.target_y == 5)
    );
}
#[test]
fn carrying_unit_never_enters_ground_flag() {
    let mut o = fixture();
    put(&mut o, 0, 5, 2, 3, true);
    o.flags.push(CtfFlag {
        id: 3,
        site_id: 7,
        x: 4,
        y: 2,
        ..CtfFlag::default()
    });
    let a = choose(&o);
    assert_ne!((a.actions[0].kind, a.actions[0].direction), (MOVE, LEFT));
}
#[test]
fn reordered_unit_array_does_not_change_actions() {
    let mut o = fixture();
    put(&mut o, 0, 6, 7, 3, false);
    o.flags.push(CtfFlag {
        id: 3,
        site_id: 7,
        x: 7,
        y: 7,
        ..CtfFlag::default()
    });
    let first = choose(&o);
    o.units.reverse();
    assert_eq!(first, choose(&o));
}

#[test]
fn carrier_avoids_a_teammates_possible_death_drop() {
    let mut o = fixture();
    put(&mut o, 0, 5, 2, 3, true);
    put(&mut o, 1, 4, 2, 1, true);
    put(&mut o, 3, 4, 4, 3, false);
    let a = choose(&o);
    assert_ne!((a.actions[0].kind, a.actions[0].direction), (MOVE, LEFT));
}

#[test]
fn ffi_rejects_null_and_allows_clean_context_recreation() {
    use std::ffi::c_void;
    let init = CtfInit {
        abi_version: ABI_VERSION,
        struct_size: std::mem::size_of::<CtfInit>() as u32,
        team_id: 0,
        team_count: 2,
        width: 15,
        height: 15,
        max_turns: 100,
        target_score: 20,
        flag_respawn_min_turns: 5,
        flag_respawn_max_turns: 15,
        first_turn: 1,
        restart_count: 0,
        seed: 3,
        decision_budget_us: 50000,
        initial_flag_count: 1,
        max_hp: 3,
        shot_damage: 1,
        shot_range: 5,
        respawn_absent_turns: 10,
    };
    let mut o = fixture();
    put(&mut o, 0, 4, 2, 3, true);
    o.turn = 20;
    let mut context = std::ptr::null_mut::<c_void>();
    let mut output = CtfTeamAction::unwritten();
    unsafe {
        assert_eq!(ctf_create(std::ptr::null(), &mut context), 1);
        assert!(context.is_null());
        assert_eq!(ctf_create(&init, &mut context), 0);
        assert!(!context.is_null());
        assert_eq!(ctf_decide(context, std::ptr::null(), &mut output), 1);
        assert_eq!(ctf_decide(context, &o.borrowed(), &mut output), 0);
        assert!(output.valid_layout());
        assert_eq!(
            (output.actions[0].kind, output.actions[0].direction),
            (MOVE, LEFT)
        );
        ctf_destroy(context);
        let mut restart = init;
        restart.first_turn = 20;
        restart.restart_count = 1;
        assert_eq!(ctf_create(&restart, &mut context), 0);
        assert_eq!(ctf_decide(context, &o.borrowed(), &mut output), 0);
        assert_eq!(output, choose(&o));
        ctf_destroy(context);
    }
}

#[test]
fn carrier_does_not_rely_on_which_carrier_the_enemy_will_shoot() {
    let mut o = fixture();
    o.homes[0].x = 4;
    o.homes[0].y = 9;
    put(&mut o, 0, 5, 5, 1, true);
    put(&mut o, 2, 5, 6, 1, true);
    put(&mut o, 3, 6, 3, 3, false);
    let a = choose(&o);
    assert_ne!((a.actions[0].kind, a.actions[0].direction), (MOVE, DOWN));
}
#[path = "drop_fixture.rs"]
mod drop_fixture;
#[test]
fn observed_multi_team_death_drop_does_not_invalidate_return_move() {
    let o = drop_fixture::observation();
    let a = choose(&o);
    assert_ne!((a.actions[0].kind, a.actions[0].direction), (MOVE, DOWN));
}

#[test]
fn equal_priority_enemies_remain_stable_when_input_is_reordered() {
    let mut o = fixture();
    put(&mut o, 0, 5, 5, 3, false);
    put(&mut o, 1, 5, 6, 3, false);
    put(&mut o, 2, 6, 5, 3, false);
    put(&mut o, 3, 7, 5, 3, false);
    put(&mut o, 4, 7, 6, 3, false);
    let first = choose(&o);
    o.units.reverse();
    assert_eq!(first, choose(&o));
}
