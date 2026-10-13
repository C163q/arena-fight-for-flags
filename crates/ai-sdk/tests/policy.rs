use fff_ai_abi::*;
fn scene() -> ObservationData {
    let mut cells = vec![0; 81];
    for y in 0..9 {
        for x in 0..9 {
            if x == 0 || y == 0 || x == 8 || y == 8 {
                cells[y * 9 + x] = 1;
            }
        }
    }
    let units = (0..6)
        .map(|i| CtfUnit {
            team_id: i / 3,
            unit_id: i % 3,
            x: -1,
            y: -1,
            ..CtfUnit::default()
        })
        .collect();
    ObservationData {
        turn: 1,
        team_id: 0,
        width: 9,
        height: 9,
        cells,
        units,
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
                x: 5,
                y: 5,
                width: 3,
                height: 3,
            },
        ],
        sites: vec![CtfSite { id: 0, x: 4, y: 4 }],
        scores: vec![0, 0],
    }
}
fn live(data: &mut ObservationData, i: usize, x: i32, y: i32) {
    data.units[i].alive = 1;
    data.units[i].hp = 3;
    data.units[i].x = x;
    data.units[i].y = y;
}
#[test]
fn carrier_routes_home_around_ground_flag_cell() {
    let mut data = scene();
    live(&mut data, 0, 4, 4);
    data.units[0].carrying = 1;
    data.units[0].flag_id = 7;
    data.flags.push(CtfFlag {
        id: 8,
        x: 3,
        y: 4,
        ..CtfFlag::default()
    });
    let raw = data.borrowed();
    let view = unsafe { view(&raw) }.unwrap();
    let actions = fff_ai_sdk::baseline(&view);
    assert_eq!(
        (actions.actions[0].kind, actions.actions[0].direction),
        (MOVE, UP)
    );
}
#[test]
fn baseline_shoots_legal_enemy_through_intermediate_friendly_unit() {
    let mut data = scene();
    live(&mut data, 0, 2, 4);
    live(&mut data, 1, 3, 4);
    live(&mut data, 3, 4, 4);
    data.units[3].hp = 1;
    let raw = data.borrowed();
    let view = unsafe { view(&raw) }.unwrap();
    let a = fff_ai_sdk::baseline(&view).actions[0];
    assert_eq!((a.kind, a.target_x, a.target_y), (SHOOT, 4, 4));
}
#[test]
fn joint_moves_do_not_compete_for_same_flag_cell() {
    let mut data = scene();
    live(&mut data, 0, 2, 4);
    live(&mut data, 1, 4, 4);
    data.flags.push(CtfFlag {
        id: 7,
        x: 3,
        y: 4,
        ..CtfFlag::default()
    });
    let raw = data.borrowed();
    let view = unsafe { view(&raw) }.unwrap();
    let actions = fff_ai_sdk::baseline(&view);
    assert!(
        !(actions.actions[0].kind == MOVE
            && actions.actions[0].direction == RIGHT
            && actions.actions[1].kind == MOVE
            && actions.actions[1].direction == LEFT)
    );
}
#[test]
fn greedy_moves_toward_flag_and_never_invents_shots() {
    let mut data = scene();
    live(&mut data, 0, 2, 4);
    data.flags.push(CtfFlag {
        id: 7,
        x: 4,
        y: 4,
        ..CtfFlag::default()
    });
    let raw = data.borrowed();
    let view = unsafe { view(&raw) }.unwrap();
    let a = fff_ai_sdk::greedy(&view).actions[0];
    assert_eq!((a.kind, a.direction), (MOVE, RIGHT));
}
