use fff_engine::map::{FlagPoint, MatchLimits, SpawnRegion};
use fff_engine::*;

fn map() -> MapDefinition {
    MapDefinition {
        format_version: 1,
        id: "test".into(),
        players: 2,
        match_limits: MatchLimits {
            target_score: 10,
            max_turns: 100,
        },
        width: 9,
        height: 9,
        terrain: (0..9)
            .map(|y| {
                if y == 0 || y == 8 {
                    "#########".into()
                } else {
                    "#.......#".into()
                }
            })
            .collect(),
        spawn_regions: vec![
            SpawnRegion {
                team_id: 0,
                x: 1,
                y: 1,
                width: 3,
                height: 3,
            },
            SpawnRegion {
                team_id: 1,
                x: 5,
                y: 5,
                width: 3,
                height: 3,
            },
        ],
        flag_points: vec![
            FlagPoint { id: 0, x: 4, y: 4 },
            FlagPoint { id: 1, x: 4, y: 1 },
            FlagPoint { id: 2, x: 1, y: 6 },
        ],
    }
}
fn scene(units: &[(usize, i32, i32, u8)]) -> Engine {
    let m = map();
    let config = Config::default();
    let mut state = Engine::new(m.clone(), config.clone(), 7)
        .unwrap()
        .snapshot()
        .clone();
    state.flags.clear();
    for site in &mut state.sites {
        site.active_flag_id = None;
        site.next_attempt_turn = Some(1000);
    }
    for u in &mut state.units {
        u.position = None;
        u.hp = 0;
        u.carrying = None;
        u.respawn_at_turn = Some(1000);
    }
    for &(i, x, y, hp) in units {
        state.units[i].position = Some(Point::new(x, y));
        state.units[i].hp = hp;
        state.units[i].respawn_at_turn = None;
    }
    Engine::from_snapshot(m, config, state).unwrap()
}
fn with_flag(e: Engine, site_id: u32, id: u64, location: FlagLocation) -> Engine {
    let mut state = e.snapshot().clone();
    if let FlagLocation::Carried { unit } = location {
        state.units[(unit.team_id * 3 + unit.unit_id) as usize].carrying = Some(id);
    }
    state.flags.push(Flag {
        id,
        site_id,
        location,
    });
    state.next_flag_id = state.next_flag_id.max(id + 1);
    let site = &mut state.sites[site_id as usize];
    site.active_flag_id = Some(id);
    site.next_attempt_turn = None;
    Engine::from_snapshot(e.map().clone(), e.config().clone(), state).unwrap()
}
fn carry(e: Engine, index: usize, site: u32, id: u64) -> Engine {
    with_flag(
        e,
        site,
        id,
        FlagLocation::Carried {
            unit: UnitId {
                team_id: index as u32 / 3,
                unit_id: index as u32 % 3,
            },
        },
    )
}
fn act(e: &mut Engine, choices: &[(usize, Action)]) -> Frame {
    let mut actions = vec![[Action::Wait; 3]; 2];
    for &(i, action) in choices {
        actions[i / 3][i % 3] = action;
    }
    e.begin_turn().unwrap();
    e.resolve_turn(actions).unwrap()
}
fn shoot(x: i32, y: i32) -> Action {
    Action::Shoot {
        target: Point::new(x, y),
    }
}
fn mv(direction: Direction) -> Action {
    Action::Move { direction }
}

#[test]
fn only_target_is_hurt_and_intermediate_unit_does_not_block() {
    let mut e = scene(&[(0, 1, 4, 3), (1, 2, 4, 3), (3, 4, 4, 3)]);
    let f = act(&mut e, &[(0, shoot(4, 4))]);
    assert_eq!(f.end.units[1].hp, 3);
    assert_eq!(f.end.units[3].hp, 2);
}
#[test]
fn manhattan_limit_rejects_diagonal_six_but_accepts_five() {
    let mut e = scene(&[(0, 1, 1, 3), (3, 4, 4, 3), (4, 4, 3, 3)]);
    let f = act(&mut e, &[(0, shoot(4, 4))]);
    assert_eq!(f.end.units[3].hp, 3);
    assert_eq!(f.applied[0][0], Action::Wait);
    let f = act(&mut e, &[(0, shoot(4, 3))]);
    assert_eq!(f.end.units[4].hp, 2);
}
#[test]
fn friendly_fire_is_valid_but_self_target_and_extreme_coordinates_are_not() {
    let mut e = scene(&[(0, 2, 2, 3), (1, 3, 2, 3)]);
    assert_eq!(act(&mut e, &[(0, shoot(3, 2))]).end.units[1].hp, 2);
    let f = act(&mut e, &[(0, shoot(2, 2))]);
    assert_eq!(f.end.units[0].hp, 3);
    assert!(
        f.events
            .iter()
            .any(|e| e.data["validation"] == "self_target")
    );
    assert_eq!(
        act(&mut e, &[(0, shoot(i32::MAX, i32::MIN))]).applied[0][0],
        Action::Wait
    );
}
#[test]
fn walls_block_even_when_segment_only_touches_corner() {
    let mut e = scene(&[(0, 4, 2, 3), (3, 5, 3, 3)]);
    let mut m = e.map().clone();
    m.terrain[2].replace_range(5..6, "#");
    e = Engine::from_snapshot(m, e.config().clone(), e.snapshot().clone()).unwrap();
    let f = act(&mut e, &[(0, shoot(5, 3))]);
    assert_eq!(f.end.units[3].hp, 3);
    assert!(f.events.iter().any(|e| e.data["result"] == "blocked"));
}
#[test]
fn shots_are_simultaneous_and_dead_mover_is_cancelled() {
    let mut e = scene(&[(0, 3, 4, 1), (3, 4, 4, 1)]);
    let f = act(&mut e, &[(0, shoot(4, 4)), (3, shoot(3, 4))]);
    assert!(f.end.units[0].position.is_none() && f.end.units[3].position.is_none());
    let mut e = scene(&[(0, 3, 4, 1), (3, 4, 4, 1)]);
    let f = act(&mut e, &[(0, mv(Direction::Up)), (3, shoot(3, 4))]);
    assert!(f.end.units[0].position.is_none());
}
#[test]
fn competing_moves_fail_while_friendly_swaps_and_empty_ended_chains_succeed() {
    let mut e = scene(&[(0, 2, 4, 3), (1, 4, 4, 3)]);
    let f = act(
        &mut e,
        &[(0, mv(Direction::Right)), (1, mv(Direction::Left))],
    );
    assert_eq!(f.end.units[0].position, Some(Point::new(2, 4)));
    assert_eq!(f.end.units[1].position, Some(Point::new(4, 4)));
    let mut e = scene(&[(0, 2, 4, 3), (1, 3, 4, 3)]);
    let f = act(
        &mut e,
        &[(0, mv(Direction::Right)), (1, mv(Direction::Left))],
    );
    assert_eq!(f.end.units[0].position, Some(Point::new(3, 4)));
    assert_eq!(f.end.units[1].position, Some(Point::new(2, 4)));
    let mut e = scene(&[(0, 2, 4, 3), (3, 3, 4, 3)]);
    let f = act(
        &mut e,
        &[(0, mv(Direction::Right)), (3, mv(Direction::Right))],
    );
    assert_eq!(f.end.units[0].position, Some(Point::new(3, 4)));
    assert_eq!(f.end.units[3].position, Some(Point::new(4, 4)));
}
#[test]
fn enemy_swap_and_mixed_cycle_fail_without_iteration_bias() {
    let mut e = scene(&[(0, 2, 4, 3), (3, 3, 4, 3)]);
    let f = act(
        &mut e,
        &[(0, mv(Direction::Right)), (3, mv(Direction::Left))],
    );
    assert_eq!(f.end.units[0].position, Some(Point::new(2, 4)));
    let mut e = scene(&[(0, 3, 3, 3), (1, 4, 3, 3), (3, 4, 4, 3), (4, 3, 4, 3)]);
    let f = act(
        &mut e,
        &[
            (0, mv(Direction::Right)),
            (1, mv(Direction::Down)),
            (3, mv(Direction::Left)),
            (4, mv(Direction::Up)),
        ],
    );
    assert_eq!(
        f.start.units.iter().map(|u| u.position).collect::<Vec<_>>(),
        f.end.units.iter().map(|u| u.position).collect::<Vec<_>>()
    );
}
#[test]
fn death_drop_blocks_carrier_before_contention_but_unladen_mover_can_pick_up() {
    let e = scene(&[(0, 3, 4, 3), (1, 4, 5, 3), (3, 4, 4, 1), (4, 5, 4, 3)]);
    let e = carry(e, 0, 0, 7);
    let mut e = carry(e, 3, 1, 8);
    let f = act(
        &mut e,
        &[
            (0, mv(Direction::Right)),
            (1, mv(Direction::Up)),
            (4, shoot(4, 4)),
        ],
    );
    assert_eq!(f.end.units[0].position, Some(Point::new(3, 4)));
    assert_eq!(f.end.units[1].position, Some(Point::new(4, 4)));
    assert_eq!(f.end.units[1].carrying, Some(8));
    assert!(
        f.events
            .iter()
            .any(|e| e.data["validation"] == "carrying_cannot_enter_flag")
    );
}
#[test]
fn carrier_cannot_shoot_and_home_return_scores_and_schedules_only_origin() {
    let e = scene(&[(0, 4, 2, 3), (3, 4, 4, 3)]);
    let mut e = carry(e, 0, 0, 7);
    assert_eq!(act(&mut e, &[(0, shoot(4, 4))]).end.units[3].hp, 3);
    let f = act(&mut e, &[(0, mv(Direction::Left))]);
    assert_eq!(f.end.scores[0], 1);
    assert_eq!(f.end.units[0].carrying, None);
    assert!(f.end.flags.is_empty());
    assert!((f.turn + 5..=f.turn + 15).contains(&f.end.sites[0].next_attempt_turn.unwrap()));
}
#[test]
fn respawn_occurs_after_ten_complete_absent_rounds_without_natural_healing() {
    let mut e = scene(&[(0, 3, 4, 1), (3, 4, 4, 2)]);
    let f = act(&mut e, &[(3, shoot(3, 4))]);
    assert_eq!(f.end.units[0].respawn_at_turn, Some(12));
    for _ in 2..=11 {
        let f = act(&mut e, &[]);
        assert!(f.start.units[0].position.is_none());
        assert_eq!(f.end.units[3].hp, 2);
    }
    let start = e.begin_turn().unwrap();
    assert!(start.units[0].position.is_some());
    assert_eq!(start.units[0].hp, 3);
}
#[test]
fn generated_flag_uses_post_move_occupancy_and_carrier_failure_resamples() {
    let mut e = scene(&[(0, 4, 3, 3)]);
    let mut state = e.snapshot().clone();
    state.sites[0].next_attempt_turn = Some(1);
    e = Engine::from_snapshot(e.map().clone(), e.config().clone(), state).unwrap();
    let f = act(&mut e, &[(0, mv(Direction::Down))]);
    assert!(f.start.flags.is_empty());
    assert!(f.end.units[0].carrying.is_some());
    assert!(f.events.iter().any(|e| e.kind == "flag_spawned"));
    let e = scene(&[(0, 4, 3, 3)]);
    let e = carry(e, 0, 1, 8);
    let mut state = e.snapshot().clone();
    state.sites[0].next_attempt_turn = Some(1);
    let mut e = Engine::from_snapshot(e.map().clone(), e.config().clone(), state).unwrap();
    let f = act(&mut e, &[(0, mv(Direction::Down))]);
    assert_eq!(f.end.units[0].position, Some(Point::new(4, 4)));
    assert_eq!(f.end.flags.len(), 1);
    assert!((6..=16).contains(&f.end.sites[0].next_attempt_turn.unwrap()));
    assert!(f.events.iter().any(|e| e.kind == "flag_spawn_failed"));
}
#[test]
fn existing_flag_survives_without_timeout_or_duplicate_origin_spawn() {
    let e = scene(&[]);
    let mut e = with_flag(
        e,
        0,
        7,
        FlagLocation::Ground {
            position: Point::new(4, 4),
        },
    );
    for _ in 0..30 {
        act(&mut e, &[]);
    }
    assert_eq!(e.snapshot().flags.len(), 1);
    assert_eq!(e.snapshot().flags[0].id, 7);
    assert_eq!(e.snapshot().sites[0].next_attempt_turn, None);
}
#[test]
fn seeded_initial_count_and_replay_actions_are_deterministic() {
    let mut a = Engine::new(map(), Config::default(), 42).unwrap();
    let mut b = Engine::new(map(), Config::default(), 42).unwrap();
    assert_eq!(a.snapshot().flags.len(), 1);
    assert_eq!(a.snapshot(), b.snapshot());
    for _ in 0..20 {
        let fa = act(&mut a, &[]);
        let fb = act(&mut b, &[]);
        assert_eq!(fa, fb);
        let mut positions = std::collections::BTreeSet::new();
        assert!(
            fa.end
                .units
                .iter()
                .filter_map(|u| u.position)
                .all(|p| positions.insert(p))
        );
    }
}
#[test]
fn map_limits_end_match_and_bad_config_or_phase_is_rejected() {
    let mut m = map();
    m.match_limits.max_turns = 1;
    let mut e = Engine::new(m, Config::default(), 7).unwrap();
    assert!(e.resolve_turn(vec![[Action::Wait; 3]; 2]).is_err());
    e.begin_turn().unwrap();
    assert!(e.begin_turn().is_err());
    let f = e.resolve_turn(vec![[Action::Wait; 3]; 2]).unwrap();
    assert!(f.end.outcome.is_some());
    assert!(e.begin_turn().is_err());
    assert!(
        Engine::new(
            map(),
            Config {
                flag_respawn_min_turns: 0,
                flag_respawn_max_turns: 15
            },
            7
        )
        .is_err()
    );
}

#[test]
fn full_birth_area_delays_respawn_until_a_cell_is_freed() {
    let m = MapDefinition::load(
        &std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../maps/arena_8p.ron"),
    )
    .unwrap();
    let mut state = Engine::new(m.clone(), Config::default(), 9)
        .unwrap()
        .snapshot()
        .clone();
    for u in &mut state.units {
        u.position = None;
        u.hp = 0;
        u.carrying = None;
        u.respawn_at_turn = Some(1000);
    }
    state.units[0].respawn_at_turn = Some(1);
    let home = &m.spawn_regions[0];
    let cells: Vec<_> = (home.y..home.y + 3)
        .flat_map(|y| (home.x..home.x + 3).map(move |x| Point::new(x as i32, y as i32)))
        .collect();
    for (i, &p) in cells.iter().enumerate() {
        let u = &mut state.units[i + 1];
        u.position = Some(p);
        u.hp = 3;
        u.respawn_at_turn = None;
    }
    let mut e = Engine::from_snapshot(m, Config::default(), state).unwrap();
    assert!(e.begin_turn().unwrap().units[0].position.is_none());
    let mut a = vec![[Action::Wait; 3]; 8];
    a[0][1] = mv(Direction::Up);
    e.resolve_turn(a).unwrap();
    let start = e.begin_turn().unwrap();
    assert_eq!(start.units[0].position, Some(cells[0]));
    assert_eq!(start.units[0].hp, 3);
}
#[test]
fn overkill_aggregates_sources_and_clamps_hp_without_negative_values() {
    let mut e = scene(&[(0, 2, 4, 3), (1, 3, 3, 3), (2, 5, 3, 3), (3, 4, 4, 1)]);
    let f = act(
        &mut e,
        &[(0, shoot(4, 4)), (1, shoot(4, 4)), (2, shoot(4, 4))],
    );
    let hp = f
        .events
        .iter()
        .find(|event| event.kind == "hp_change")
        .unwrap();
    assert_eq!(hp.data["damage"], 3);
    assert_eq!(hp.data["after"], 0);
    assert_eq!(hp.data["sources"].as_array().unwrap().len(), 3);
    assert!(f.end.units[3].position.is_none());
}
#[test]
fn opening_flag_count_uses_rounded_minimum_for_small_maps() {
    let candidates = [
        (4, 1),
        (5, 1),
        (6, 1),
        (7, 1),
        (4, 2),
        (5, 2),
        (6, 2),
        (7, 2),
        (4, 3),
    ];
    for (n, want) in [
        (1, 1),
        (2, 1),
        (3, 1),
        (4, 1),
        (5, 2),
        (6, 2),
        (7, 2),
        (8, 3),
        (9, 3),
    ] {
        let mut m = map();
        m.flag_points = candidates[..n]
            .iter()
            .enumerate()
            .map(|(i, &(x, y))| FlagPoint { id: i as u32, x, y })
            .collect();
        let e = Engine::new(m, Config::default(), 8).unwrap();
        assert_eq!(e.snapshot().flags.len(), want);
    }
}
#[test]
fn home_return_schedule_event_belongs_to_score_phase_and_targets_spawn_phase() {
    let e = scene(&[(0, 4, 2, 3)]);
    let mut e = carry(e, 0, 0, 7);
    let f = act(&mut e, &[(0, mv(Direction::Left))]);
    let schedule = f
        .events
        .iter()
        .find(|e| e.kind == "flag_respawn_scheduled")
        .unwrap();
    assert_eq!(schedule.phase, "score");
    assert_eq!(schedule.data["next_attempt_phase"], "flag_spawn");
}

#[test]
fn move_cancelled_by_same_turn_death_is_not_a_submission_error() {
    let mut e = scene(&[(0, 3, 4, 1), (3, 4, 4, 3)]);
    let frame = act(&mut e, &[(0, mv(Direction::Up)), (3, shoot(3, 4))]);
    let event = frame.events.iter().find(|e| e.kind == "move").unwrap();
    assert_eq!(event.data["validation"], "ok");
    assert_eq!(event.data["result"], "cancelled");
    assert_eq!(event.data["from"], serde_json::json!({"x":3,"y":4}));
    assert_eq!(event.data["target"], serde_json::json!({"x":3,"y":3}));
}
