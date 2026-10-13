mod host;
pub mod protocol;
use fff_ai_abi::*;
use fff_engine::*;
pub use host::TeamHost;
use serde::{Deserialize, Serialize};
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CallReport {
    pub team_id: u32,
    pub turn: u32,
    pub status: String,
    pub elapsed_us: u64,
    pub init_elapsed_us: u64,
    pub restart_count: u32,
    pub actions: TeamActions,
    pub raw_output: Option<CtfTeamAction>,
    pub error: Option<String>,
}
pub fn initialization(map: &MapDefinition, config: &Config, team: u32, seed: u64) -> CtfInit {
    CtfInit {
        abi_version: ABI_VERSION,
        struct_size: std::mem::size_of::<CtfInit>() as u32,
        team_id: team,
        team_count: map.players,
        width: map.width,
        height: map.height,
        max_turns: map.match_limits.max_turns,
        target_score: map.match_limits.target_score,
        flag_respawn_min_turns: config.flag_respawn_min_turns,
        flag_respawn_max_turns: config.flag_respawn_max_turns,
        first_turn: 1,
        restart_count: 0,
        seed,
        decision_budget_us: 50_000,
        initial_flag_count: ((map.flag_points.len() + 1) / 3).max(1) as u32,
        max_hp: 3,
        shot_damage: 1,
        shot_range: 5,
        respawn_absent_turns: 10,
    }
}
pub fn observation(snapshot: &Snapshot, map: &MapDefinition, team: u32) -> ObservationData {
    ObservationData {
        turn: snapshot.turn,
        team_id: team,
        width: map.width,
        height: map.height,
        cells: map
            .terrain
            .iter()
            .flat_map(|r| r.bytes().map(|c| u8::from(c == b'#')))
            .collect(),
        units: snapshot
            .units
            .iter()
            .map(|u| CtfUnit {
                team_id: u.id.team_id,
                unit_id: u.id.unit_id,
                alive: u32::from(u.position.is_some()),
                hp: u.hp.into(),
                x: u.position.map_or(-1, |p| p.x),
                y: u.position.map_or(-1, |p| p.y),
                carrying: u32::from(u.carrying.is_some()),
                respawn_at_turn: u.respawn_at_turn.unwrap_or(0),
                flag_id: u.carrying.unwrap_or(0),
            })
            .collect(),
        flags: snapshot
            .flags
            .iter()
            .map(|f| {
                let (state, x, y, t, u) = match f.location {
                    FlagLocation::Ground { position } => {
                        (0, position.x, position.y, u32::MAX, u32::MAX)
                    }
                    FlagLocation::Carried { unit } => {
                        let p = snapshot.units[(unit.team_id * 3 + unit.unit_id) as usize]
                            .position
                            .expect("live carrier");
                        (1, p.x, p.y, unit.team_id, unit.unit_id)
                    }
                };
                CtfFlag {
                    id: f.id,
                    site_id: f.site_id,
                    state,
                    x,
                    y,
                    carrier_team: t,
                    carrier_unit: u,
                }
            })
            .collect(),
        homes: map
            .spawn_regions
            .iter()
            .map(|s| CtfHome {
                team_id: s.team_id,
                x: s.x as i32,
                y: s.y as i32,
                width: s.width,
                height: s.height,
            })
            .collect(),
        sites: map
            .flag_points
            .iter()
            .map(|s| CtfSite {
                id: s.id,
                x: s.x as i32,
                y: s.y as i32,
            })
            .collect(),
        scores: snapshot.scores.clone(),
    }
}
fn decode(a: CtfAction) -> Action {
    match a.kind {
        WAIT => Action::Wait,
        MOVE => match a.direction {
            UP => Action::Move {
                direction: Direction::Up,
            },
            DOWN => Action::Move {
                direction: Direction::Down,
            },
            LEFT => Action::Move {
                direction: Direction::Left,
            },
            RIGHT => Action::Move {
                direction: Direction::Right,
            },
            _ => Action::Invalid {
                kind_code: a.kind,
                direction_code: a.direction,
                target: Point::new(a.target_x, a.target_y),
            },
        },
        SHOOT => Action::Shoot {
            target: Point::new(a.target_x, a.target_y),
        },
        _ => Action::Invalid {
            kind_code: a.kind,
            direction_code: a.direction,
            target: Point::new(a.target_x, a.target_y),
        },
    }
}
