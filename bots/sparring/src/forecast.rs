use crate::board::NONE;

#[derive(Clone)]
pub struct State {
    pub pos: [usize; 24],
    pub hp: [u32; 24],
    pub carry: [bool; 24],
    pub team: [u32; 24],
    pub count: usize,
    // Count rather than bool: multiple dropped flags may share a cell.
    pub ground: Vec<u8>,
}
impl State {
    pub fn damage(&mut self, hits: &[u32; 24]) {
        for (v, &hit) in hits.iter().enumerate().take(self.count) {
            if self.pos[v] == NONE {
                continue;
            }
            self.hp[v] = self.hp[v].saturating_sub(hit);
            if self.hp[v] == 0 {
                if self.carry[v] {
                    self.ground[self.pos[v]] += 1;
                }
                self.pos[v] = NONE;
                self.carry[v] = false;
            }
        }
    }
    pub fn movement(&mut self, desired: &[usize; 24]) {
        let mut dest = *desired;
        for (v, p) in dest.iter_mut().enumerate().take(self.count) {
            if self.pos[v] == NONE {
                *p = NONE;
            } else if *p == NONE || *p >= self.ground.len() || self.carry[v] && self.ground[*p] > 0
            {
                *p = self.pos[v];
            }
        }
        let mut allowed = [true; 24];
        for v in 0..self.count {
            if self.pos[v] == NONE || dest[v] == self.pos[v] {
                allowed[v] = false;
                continue;
            }
            for j in 0..self.count {
                if v != j && dest[v] == dest[j] && dest[j] != self.pos[j] {
                    allowed[v] = false;
                }
            }
        }
        // Resolve dependency chains; reject mixed-team cycles irrespective of iteration order.
        for start in 0..self.count {
            if !allowed[start] {
                continue;
            }
            let mut chain = Vec::with_capacity(24);
            let mut at = start;
            let succeeds = loop {
                if let Some(k) = chain.iter().position(|&v| v == at) {
                    break chain[k..].iter().all(|&v| self.team[v] == self.team[at]);
                }
                if !allowed[at] {
                    break false;
                }
                chain.push(at);
                if let Some(next) =
                    (0..self.count).find(|&v| self.pos[v] != NONE && self.pos[v] == dest[at])
                {
                    at = next;
                } else {
                    break true;
                }
            };
            if !succeeds {
                for v in chain {
                    allowed[v] = false;
                }
            }
        }
        for v in 0..self.count {
            if allowed[v] {
                self.pos[v] = dest[v];
            }
        }
    }
    pub fn collect(&mut self, home: &[Vec<u16>]) -> ([bool; 24], [bool; 24]) {
        let mut picked = [false; 24];
        let mut delivered = [false; 24];
        for v in 0..self.count {
            let p = self.pos[v];
            if p == NONE {
                continue;
            }
            if !self.carry[v] && self.ground[p] > 0 {
                self.carry[v] = true;
                self.ground[p] -= 1;
                picked[v] = true;
            }
            if self.carry[v] && home[self.team[v] as usize][p] == 0 {
                self.carry[v] = false;
                delivered[v] = true;
            }
        }
        (picked, delivered)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn state() -> State {
        let mut s = State {
            pos: [NONE; 24],
            hp: [0; 24],
            carry: [false; 24],
            team: [0; 24],
            count: 3,
            ground: vec![0; 81],
        };
        s.pos[..3].copy_from_slice(&[30, 31, 32]);
        s.hp[..3].fill(3);
        s
    }
    #[test]
    fn friendly_cycles_and_chains_move_but_mixed_cycles_do_not() {
        let mut s = state();
        let mut d = s.pos;
        d[0] = 31;
        d[1] = 30;
        s.movement(&d);
        assert_eq!(&s.pos[..3], &[31, 30, 32]);
        let mut s = state();
        s.team[1] = 1;
        let mut d = s.pos;
        d[0] = 31;
        d[1] = 30;
        s.movement(&d);
        assert_eq!(&s.pos[..3], &[30, 31, 32]);
        let mut s = state();
        let mut d = s.pos;
        d[0] = 31;
        d[1] = 32;
        d[2] = 33;
        s.movement(&d);
        assert_eq!(&s.pos[..3], &[31, 32, 33]);
    }
    #[test]
    fn same_destination_blocks_every_contender() {
        let mut s = state();
        let mut d = s.pos;
        d[0] = 40;
        d[1] = 40;
        s.movement(&d);
        assert_eq!(&s.pos[..3], &[30, 31, 32]);
    }
    #[test]
    fn death_drops_flag_before_carrier_movement() {
        let mut s = state();
        s.carry[0] = true;
        s.carry[1] = true;
        s.hp[0] = 1;
        let mut hits = [0; 24];
        hits[0] = 1;
        s.damage(&hits);
        assert_eq!(s.pos[0], NONE);
        assert_eq!(s.ground[30], 1);
        let mut d = s.pos;
        d[1] = 30;
        s.movement(&d);
        assert_eq!(s.pos[1], 31);
    }
}

#[cfg(test)]
mod differential_tests {
    use super::*;
    use fff_engine::{
        Action, Config, Direction, Engine, MapDefinition, Point,
        map::{FlagPoint, MatchLimits, SpawnRegion},
    };
    #[test]
    fn crowded_movement_matches_engine_for_independent_action_sets() {
        let map = MapDefinition {
            format_version: 1,
            id: "forecast_test".into(),
            players: 2,
            width: 15,
            height: 15,
            match_limits: MatchLimits {
                target_score: 20,
                max_turns: 10,
            },
            terrain: (0..15)
                .map(|y| {
                    if y == 0 || y == 14 {
                        "#".repeat(15)
                    } else {
                        format!("#{}#", ".".repeat(13))
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
                    x: 11,
                    y: 11,
                    width: 3,
                    height: 3,
                },
            ],
            flag_points: vec![FlagPoint { id: 0, x: 7, y: 7 }],
        };
        let initial = Engine::new(map.clone(), Config::default(), 1)
            .unwrap()
            .snapshot()
            .clone();
        let mut seed = 881u64;
        let mut draw = || {
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
            (seed >> 32) as usize
        };
        for case in 0..400 {
            let mut start = initial.clone();
            let mut forecast = State {
                pos: [NONE; 24],
                hp: [0; 24],
                carry: [false; 24],
                team: [0; 24],
                count: 6,
                ground: vec![0; 225],
            };
            for i in 0..6 {
                let p = loop {
                    let p = (5 + draw() % 4) * 15 + 5 + draw() % 4;
                    if !forecast.pos.contains(&p) {
                        break p;
                    }
                };
                forecast.pos[i] = p;
                forecast.hp[i] = 3;
                forecast.team[i] = (i / 3) as u32;
                start.units[i].position = Some(Point::new((p % 15) as i32, (p / 15) as i32));
            }
            let mut desired = forecast.pos;
            let mut actions = vec![[Action::Wait; 3]; 2];
            for i in 0..6 {
                let p = forecast.pos[i];
                let choice = draw() % 5;
                if choice < 4 {
                    let (delta, direction) = match choice {
                        0 => (-15, Direction::Up),
                        1 => (15, Direction::Down),
                        2 => (-1, Direction::Left),
                        _ => (1, Direction::Right),
                    };
                    desired[i] = (p as isize + delta) as usize;
                    actions[i / 3][i % 3] = Action::Move { direction };
                }
            }
            let mut engine = Engine::from_snapshot(map.clone(), Config::default(), start).unwrap();
            engine.begin_turn().unwrap();
            let frame = engine.resolve_turn(actions).unwrap();
            forecast.movement(&desired);
            for i in 0..6 {
                let p = frame.end.units[i].position.unwrap();
                assert_eq!(
                    forecast.pos[i],
                    p.y as usize * 15 + p.x as usize,
                    "case {case} unit {i}"
                );
            }
        }
    }
}
