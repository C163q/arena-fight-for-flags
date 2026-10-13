use crate::{flags, movement, rng::Rng, shooting, *};
use serde_json::json;
use std::collections::BTreeSet;

pub struct Engine {
    pub(crate) map: MapDefinition,
    pub(crate) config: Config,
    pub(crate) state: Snapshot,
    pub(crate) rng: Rng,
    pub(crate) events: Vec<Event>,
    start: Option<Snapshot>,
}
impl Engine {
    pub fn new(mut map: MapDefinition, config: Config, seed: u64) -> Result<Self, String> {
        map.validate()?;
        validate_config(&config)?;
        map.spawn_regions.sort_by_key(|s| s.team_id);
        map.flag_points.sort_by_key(|s| s.id);
        let sites = map
            .flag_points
            .iter()
            .map(|p| SiteState {
                site_id: p.id,
                active_flag_id: None,
                next_attempt_turn: None,
                origin: "initial".into(),
                scheduled_by: None,
            })
            .collect();
        let mut e = Self {
            state: Snapshot {
                turn: 0,
                scores: vec![0; map.players as usize],
                units: Vec::new(),
                flags: Vec::new(),
                sites,
                rng_state: seed,
                next_flag_id: 1,
                outcome: None,
            },
            map,
            config,
            rng: Rng(seed),
            events: Vec::new(),
            start: None,
        };
        for team in 0..e.map.players {
            for unit_id in 0..3 {
                let choices = e.free_home(team);
                let p = choices[e.rng.below(choices.len() as u64) as usize];
                e.state.units.push(Unit {
                    id: UnitId {
                        team_id: team,
                        unit_id,
                    },
                    position: Some(p),
                    hp: MAX_HP,
                    carrying: None,
                    respawn_at_turn: None,
                });
            }
        }
        let mut order: Vec<usize> = (0..e.map.flag_points.len()).collect();
        for i in (1..order.len()).rev() {
            let j = e.rng.below((i + 1) as u64) as usize;
            order.swap(i, j);
        }
        let count = ((order.len() + 1) / 3).max(1);
        let selected: BTreeSet<_> = order.into_iter().take(count).collect();
        for i in 0..e.state.sites.len() {
            if selected.contains(&i) {
                flags::spawn(&mut e, i, "initial");
            } else {
                let d = e.delay();
                e.state.sites[i].next_attempt_turn = Some(d);
            }
        }
        e.events.clear();
        e.sync_rng();
        Ok(e)
    }
    pub fn from_snapshot(
        mut map: MapDefinition,
        config: Config,
        state: Snapshot,
    ) -> Result<Self, String> {
        map.validate()?;
        validate_config(&config)?;
        map.spawn_regions.sort_by_key(|s| s.team_id);
        map.flag_points.sort_by_key(|s| s.id);
        validate_snapshot(&map, &state)?;
        let rng = Rng(state.rng_state);
        Ok(Self {
            map,
            config,
            state,
            rng,
            events: Vec::new(),
            start: None,
        })
    }
    pub fn begin_turn(&mut self) -> Result<Snapshot, String> {
        if self.start.is_some() {
            return Err("turn already started".into());
        }
        if self.state.outcome.is_some() || self.state.turn >= self.map.match_limits.max_turns {
            return Err("match has ended".into());
        }
        self.state.turn += 1;
        self.events.clear();
        for i in 0..self.state.units.len() {
            if self.state.units[i].position.is_some()
                || self.state.units[i]
                    .respawn_at_turn
                    .is_none_or(|t| t > self.state.turn)
            {
                continue;
            }
            let id = self.state.units[i].id;
            let choices = self.free_home(id.team_id);
            if choices.is_empty() {
                self.state.units[i].respawn_at_turn = Some(self.state.turn + 1);
                self.emit(
                    "start",
                    "respawn_blocked",
                    json!({"unit":id,"retry_at_turn":self.state.turn+1}),
                );
            } else {
                let p = choices[self.rng.below(choices.len() as u64) as usize];
                let u = &mut self.state.units[i];
                u.position = Some(p);
                u.hp = MAX_HP;
                u.carrying = None;
                u.respawn_at_turn = None;
                self.emit(
                    "start",
                    "respawn",
                    json!({"unit":id,"position":p,"hp":MAX_HP}),
                );
            }
        }
        self.sync_rng();
        let start = self.state.clone();
        self.start = Some(start.clone());
        Ok(start)
    }
    pub fn resolve_turn(&mut self, actions: Vec<TeamActions>) -> Result<Frame, String> {
        if self.start.is_none() {
            return Err("begin_turn must precede resolve_turn".into());
        }
        if actions.len() != self.map.players as usize {
            return Err("team action count mismatch".into());
        }
        let start = self.start.take().expect("checked start");
        let mut applied = actions.clone();
        for i in 0..self.state.units.len() {
            if matches!(applied[i / 3][i % 3], Action::Invalid { .. }) {
                self.emit("validation","action_invalid",json!({"unit":self.state.units[i].id,"validation":"unknown_action","submitted":applied[i/3][i%3]}));
                applied[i / 3][i % 3] = Action::Wait;
            }
        }
        shooting::resolve(self, &mut applied);
        movement::resolve(self, &mut applied, &start);
        flags::pickup_existing(self);
        flags::generate_due(self);
        flags::score(self);
        if self.state.turn >= self.map.match_limits.max_turns
            || self
                .state
                .scores
                .iter()
                .any(|s| *s >= self.map.match_limits.target_score)
        {
            let high = *self.state.scores.iter().max().expect("teams");
            let winners = self
                .state
                .scores
                .iter()
                .enumerate()
                .filter_map(|(i, &s)| (s == high).then_some(i as u32))
                .collect();
            self.state.outcome = Some(Outcome {
                winners,
                reason: if self
                    .state
                    .scores
                    .iter()
                    .any(|s| *s >= self.map.match_limits.target_score)
                {
                    "target_score"
                } else {
                    "max_turns"
                }
                .into(),
            });
        }
        self.sync_rng();
        validate_snapshot(&self.map, &self.state)?;
        Ok(Frame {
            turn: self.state.turn,
            start,
            requested: actions,
            applied,
            events: std::mem::take(&mut self.events),
            end: self.state.clone(),
        })
    }
    pub fn snapshot(&self) -> &Snapshot {
        &self.state
    }
    pub fn map(&self) -> &MapDefinition {
        &self.map
    }
    pub fn config(&self) -> &Config {
        &self.config
    }
    pub(crate) fn emit(&mut self, phase: &str, kind: &str, data: serde_json::Value) -> String {
        let event_id = format!("t{}.{}.{}", self.state.turn, phase, self.events.len());
        self.events.push(Event {
            event_id: event_id.clone(),
            phase: phase.into(),
            kind: kind.into(),
            data,
        });
        event_id
    }
    pub(crate) fn delay(&mut self) -> u32 {
        self.config.flag_respawn_min_turns
            + self.rng.below(
                u64::from(self.config.flag_respawn_max_turns - self.config.flag_respawn_min_turns)
                    + 1,
            ) as u32
    }
    pub(crate) fn occupied(&self, p: Point) -> Option<usize> {
        self.state.units.iter().position(|u| u.position == Some(p))
    }
    pub(crate) fn free_home(&self, team: u32) -> Vec<Point> {
        let s = &self.map.spawn_regions[team as usize];
        let mut free = Vec::new();
        for y in s.y..s.y + 3 {
            for x in s.x..s.x + 3 {
                let p = Point::new(x as i32, y as i32);
                if self.occupied(p).is_none() {
                    free.push(p);
                }
            }
        }
        free
    }
    fn sync_rng(&mut self) {
        self.state.rng_state = self.rng.0;
    }
}
fn validate_config(c: &Config) -> Result<(), String> {
    if c.flag_respawn_min_turns == 0
        || c.flag_respawn_min_turns > c.flag_respawn_max_turns
        || c.flag_respawn_max_turns > 1_000_000
    {
        Err("invalid flag respawn interval".into())
    } else {
        Ok(())
    }
}
pub fn validate_snapshot(map: &MapDefinition, s: &Snapshot) -> Result<(), String> {
    if s.units.len() != map.players as usize * 3
        || s.scores.len() != map.players as usize
        || s.sites.len() != map.flag_points.len()
    {
        return Err("snapshot object count mismatch".into());
    }
    let mut positions = BTreeSet::new();
    let mut ids = BTreeSet::new();
    let mut source_ids = BTreeSet::new();
    for (i, u) in s.units.iter().enumerate() {
        if u.id
            != (UnitId {
                team_id: i as u32 / 3,
                unit_id: i as u32 % 3,
            })
        {
            return Err("unstable unit ID".into());
        }
        if let Some(p) = u.position {
            if !map.is_walkable(p)
                || !positions.insert(p)
                || u.hp == 0
                || u.hp > MAX_HP
                || u.respawn_at_turn.is_some()
            {
                return Err("invalid live unit".into());
            }
        } else if u.hp != 0 || u.carrying.is_some() || u.respawn_at_turn.is_none() {
            return Err("invalid dead unit".into());
        }
    }
    for flag in &s.flags {
        if !ids.insert(flag.id) || !source_ids.insert(flag.site_id) || flag.id >= s.next_flag_id {
            return Err("duplicate flag or invalid next flag ID".into());
        }
        let site = s
            .sites
            .iter()
            .find(|p| p.site_id == flag.site_id)
            .ok_or("flag has unknown source")?;
        if site.active_flag_id != Some(flag.id) || site.next_attempt_turn.is_some() {
            return Err("flag source link mismatch".into());
        }
        match flag.location {
            FlagLocation::Ground { position } => {
                if !map.is_walkable(position) {
                    return Err("ground flag in wall".into());
                }
            }
            FlagLocation::Carried { unit } => {
                let u = s
                    .units
                    .get(
                        (unit.team_id as usize)
                            .saturating_mul(3)
                            .saturating_add(unit.unit_id as usize),
                    )
                    .ok_or("invalid flag carrier")?;
                if u.id != unit || u.carrying != Some(flag.id) || u.position.is_none() {
                    return Err("flag carrier mismatch".into());
                }
            }
        }
    }
    for u in &s.units {
        if let Some(id) = u.carrying
            && !s
                .flags
                .iter()
                .any(|f| f.id == id && f.location == FlagLocation::Carried { unit: u.id })
        {
            return Err("unit flag link mismatch".into());
        }
    }
    let mut site_ids = BTreeSet::new();
    for site in &s.sites {
        if !site_ids.insert(site.site_id) || !map.flag_points.iter().any(|p| p.id == site.site_id) {
            return Err("unknown/duplicate site".into());
        }
        if let Some(id) = site.active_flag_id {
            if !s
                .flags
                .iter()
                .any(|f| f.id == id && f.site_id == site.site_id)
            {
                return Err("site active flag missing".into());
            }
        } else if site.next_attempt_turn.is_none() {
            return Err("inactive site missing schedule".into());
        }
    }
    Ok(())
}
