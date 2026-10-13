use serde::{Deserialize, Serialize};

pub const MAX_HP: u8 = 3;
pub const DAMAGE: u8 = 1;
pub const RANGE: u32 = 5;
pub const RESPAWN_ABSENT_TURNS: u32 = 10;
pub const RULES_VERSION: &str = "fff-rules-v1";

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
pub struct Point {
    pub x: i32,
    pub y: i32,
}
impl Point {
    pub const fn new(x: i32, y: i32) -> Self {
        Self { x, y }
    }
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
pub struct UnitId {
    pub team_id: u32,
    pub unit_id: u32,
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Direction {
    Up,
    Down,
    Left,
    Right,
}
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Action {
    #[default]
    Wait,
    Move {
        direction: Direction,
    },
    Shoot {
        target: Point,
    },
    Invalid {
        kind_code: u32,
        direction_code: u32,
        target: Point,
    },
}
pub type TeamActions = [Action; 3];
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub flag_respawn_min_turns: u32,
    pub flag_respawn_max_turns: u32,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            flag_respawn_min_turns: 5,
            flag_respawn_max_turns: 15,
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Unit {
    pub id: UnitId,
    pub position: Option<Point>,
    pub hp: u8,
    pub carrying: Option<u64>,
    pub respawn_at_turn: Option<u32>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum FlagLocation {
    Ground { position: Point },
    Carried { unit: UnitId },
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Flag {
    pub id: u64,
    pub site_id: u32,
    pub location: FlagLocation,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct SiteState {
    pub site_id: u32,
    pub active_flag_id: Option<u64>,
    pub next_attempt_turn: Option<u32>,
    pub origin: String,
    pub scheduled_by: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Outcome {
    pub winners: Vec<u32>,
    pub reason: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Snapshot {
    pub turn: u32,
    pub scores: Vec<u32>,
    pub units: Vec<Unit>,
    pub flags: Vec<Flag>,
    pub sites: Vec<SiteState>,
    pub rng_state: u64,
    pub next_flag_id: u64,
    pub outcome: Option<Outcome>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Event {
    pub event_id: String,
    pub phase: String,
    #[serde(rename = "type")]
    pub kind: String,
    #[serde(flatten)]
    pub data: serde_json::Value,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Frame {
    pub turn: u32,
    pub start: Snapshot,
    pub requested: Vec<TeamActions>,
    pub applied: Vec<TeamActions>,
    pub events: Vec<Event>,
    pub end: Snapshot,
}
