use crate::Point;
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeSet, VecDeque},
    fs::File,
    io::Read,
    path::Path,
};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct MatchLimits {
    pub target_score: u32,
    pub max_turns: u32,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct SpawnRegion {
    pub team_id: u32,
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct FlagPoint {
    pub id: u32,
    pub x: u32,
    pub y: u32,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct MapDefinition {
    pub format_version: u32,
    pub id: String,
    pub players: u32,
    pub match_limits: MatchLimits,
    pub width: u32,
    pub height: u32,
    pub terrain: Vec<String>,
    pub spawn_regions: Vec<SpawnRegion>,
    pub flag_points: Vec<FlagPoint>,
}
impl MapDefinition {
    pub fn load(path: &Path) -> Result<Self, String> {
        let mut text = String::new();
        File::open(path)
            .map_err(|e| format!("{}: {e}", path.display()))?
            .take(1_048_577)
            .read_to_string(&mut text)
            .map_err(|e| format!("{}: {e}", path.display()))?;
        if text.len() > 1_048_576 {
            return Err("map exceeds 1 MiB".into());
        }
        let map: Self = ron::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))?;
        map.validate()
            .map_err(|e| format!("{}: {e}", path.display()))?;
        Ok(map)
    }
    pub fn validate(&self) -> Result<(), String> {
        if self.format_version != 1 {
            return Err("unsupported map format_version".into());
        }
        if self.id.is_empty()
            || self.id.len() > 64
            || !self
                .id
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
        {
            return Err("map id must be 1–64 ASCII identifier characters".into());
        }
        if !(2..=8).contains(&self.players)
            || !(9..=128).contains(&self.width)
            || !(9..=128).contains(&self.height)
        {
            return Err("players must be 2–8 and dimensions 9–128".into());
        }
        if self.match_limits.target_score == 0
            || self.match_limits.max_turns == 0
            || self.match_limits.max_turns > 1_000_000
        {
            return Err(
                "match_limits require positive target_score and max_turns in 1..=1000000".into(),
            );
        }
        if self.terrain.len() != self.height as usize {
            return Err("terrain height mismatch".into());
        }
        for (y, row) in self.terrain.iter().enumerate() {
            if row.len() != self.width as usize || !row.bytes().all(|b| b == b'#' || b == b'.') {
                return Err(format!("invalid terrain row {y}"));
            }
            for (x, c) in row.bytes().enumerate() {
                if (x == 0
                    || y == 0
                    || x + 1 == self.width as usize
                    || y + 1 == self.height as usize)
                    && c != b'#'
                {
                    return Err(format!("border not sealed at ({x},{y})"));
                }
            }
        }
        if self.spawn_regions.len() != self.players as usize {
            return Err("spawn region count mismatch".into());
        }
        let mut teams = BTreeSet::new();
        let mut homes = BTreeSet::new();
        for s in &self.spawn_regions {
            if s.team_id >= self.players
                || !teams.insert(s.team_id)
                || s.width != 3
                || s.height != 3
                || s.x > self.width - 4
                || s.y > self.height - 4
            {
                return Err("invalid spawn region ID, size or bounds".into());
            }
            for y in s.y..s.y + 3 {
                for x in s.x..s.x + 3 {
                    let p = Point::new(x as i32, y as i32);
                    if !self.is_walkable(p) || !homes.insert(p) {
                        return Err(format!("wall or overlap in home at ({x},{y})"));
                    }
                }
            }
        }
        if self.flag_points.is_empty() || self.flag_points.len() > 32 {
            return Err("flag point count must be 1–32".into());
        }
        let mut ids = BTreeSet::new();
        let mut points = BTreeSet::new();
        for f in &self.flag_points {
            if f.x >= self.width || f.y >= self.height {
                return Err("flag point out of bounds".into());
            }
            let p = Point::new(f.x as i32, f.y as i32);
            if !ids.insert(f.id) || !points.insert(p) || !self.is_walkable(p) || homes.contains(&p)
            {
                return Err("duplicate, blocked or home flag point".into());
            }
        }
        let start = *homes.first().ok_or("missing homes")?;
        let mut seen = BTreeSet::from([start]);
        let mut queue = VecDeque::from([start]);
        while let Some(p) = queue.pop_front() {
            for (dx, dy) in [(0, -1), (1, 0), (0, 1), (-1, 0)] {
                let q = Point::new(p.x + dx, p.y + dy);
                if self.is_walkable(q) && seen.insert(q) {
                    queue.push_back(q);
                }
            }
        }
        let floors = self
            .terrain
            .iter()
            .map(|r| r.bytes().filter(|&c| c == b'.').count())
            .sum::<usize>();
        if seen.len() != floors {
            return Err("walkable floor is not connected".into());
        }
        Ok(())
    }
    pub fn contains(&self, p: Point) -> bool {
        p.x >= 0 && p.y >= 0 && (p.x as u32) < self.width && (p.y as u32) < self.height
    }
    pub fn is_walkable(&self, p: Point) -> bool {
        self.contains(p) && self.terrain[p.y as usize].as_bytes()[p.x as usize] == b'.'
    }
    pub fn is_home(&self, team: u32, p: Point) -> bool {
        self.spawn_regions.iter().any(|s| {
            s.team_id == team
                && p.x >= s.x as i32
                && p.y >= s.y as i32
                && p.x < (s.x + 3) as i32
                && p.y < (s.y + 3) as i32
        })
    }
}
