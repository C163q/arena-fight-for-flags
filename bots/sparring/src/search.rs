use crate::{
    Bot,
    board::{Board, NONE},
    forecast::State,
    objectives::{Goal, route},
};
use fff_ai_abi::*;

#[derive(Clone, Copy)]
struct OptionMove {
    kind: u32,
    dir: u32,
    pos: usize,
    target: usize,
    base: f32,
}
#[derive(Clone, Copy)]
pub struct Volley {
    pub hits: [u32; 24],
    pub target: [usize; 3],
    pub value: f32,
}

fn hit_value(s: &State, e: usize, hits: u32) -> f32 {
    if e == NONE {
        return 0.;
    }
    if hits > s.hp[e] {
        return -1.5;
    }
    let carry = s.carry[e] as u32 as f32;
    2.5 + 1.8 * carry
        + if hits == s.hp[e] {
            6. + 11. * carry
        } else {
            0.
        }
}

pub fn volley(b: &Board, s: &State, team: u32) -> Volley {
    let mut candidates: [Vec<usize>; 3] = std::array::from_fn(|_| vec![NONE]);
    for v in 0..s.count {
        if s.team[v] != team || s.pos[v] == NONE || s.carry[v] {
            continue;
        }
        // Observation array order is not an ABI guarantee; choose stable per-team slots.
        let slot = (0..v).filter(|&z| s.team[z] == team).count();
        for e in 0..s.count {
            if s.team[e] != team && s.pos[e] != NONE && b.sight(s.pos[v], s.pos[e]) {
                candidates[slot].push(e);
            }
        }
        candidates[slot].sort_by(|&a, &c| {
            let priority = |e: usize| {
                if e == NONE {
                    -100.
                } else {
                    3. * s.carry[e] as u32 as f32 + 2. / s.hp[e] as f32
                }
            };
            priority(c).total_cmp(&priority(a))
        });
        candidates[slot].truncate(6);
        if !candidates[slot].contains(&NONE) {
            candidates[slot].push(NONE);
        }
    }
    let mut best = Volley {
        hits: [0; 24],
        target: [NONE; 3],
        value: -1e20,
    };
    let mut hits = [0; 24];
    for &a in &candidates[0] {
        if a != NONE {
            hits[a] += 1;
        }
        let va = hit_value(s, a, if a == NONE { 0 } else { hits[a] });
        for &c in &candidates[1] {
            if c != NONE {
                hits[c] += 1;
            }
            let vc = hit_value(s, c, if c == NONE { 0 } else { hits[c] });
            for &d in &candidates[2] {
                if d != NONE {
                    hits[d] += 1;
                }
                let val = va + vc + hit_value(s, d, if d == NONE { 0 } else { hits[d] });
                if val > best.value {
                    best = Volley {
                        hits,
                        target: [a, c, d],
                        value: val,
                    };
                }
                if d != NONE {
                    hits[d] -= 1;
                }
            }
            if c != NONE {
                hits[c] -= 1;
            }
        }
        if a != NONE {
            hits[a] -= 1;
        }
    }
    best
}

impl Bot {
    fn predicted_moves(
        &self,
        s: &State,
        shots: &[Volley],
        goals: &[Goal],
        mine: &[usize; 3],
        assigned: &[usize; 3],
    ) -> [usize; 24] {
        let b = self.board.as_ref().unwrap();
        let mut next = s.pos;
        for (v, destination) in next.iter_mut().enumerate().take(s.count) {
            let p = s.pos[v];
            if p == NONE {
                continue;
            }
            let team = s.team[v] as usize;
            let slot = (0..v).filter(|&z| s.team[z] == s.team[v]).count();
            if shots[team].target[slot] != NONE {
                continue;
            }
            let own = team == self.team;
            let goal = if own {
                let i = mine.iter().position(|&e| e == v).unwrap();
                goals[assigned[i]].pos
            } else {
                s.ground
                    .iter()
                    .enumerate()
                    .filter(|(_, count)| **count > 0)
                    .min_by_key(|(q, _)| b.distance(p, *q) as u32 + self.home[team][*q] as u32 / 3)
                    .map(|(q, _)| q)
                    .or_else(|| {
                        goals
                            .iter()
                            .filter(|g| !g.ground)
                            .min_by_key(|g| {
                                b.distance(p, g.pos) as u32
                                    + (g.wait * 0.4) as u32
                                    + self.home[team][g.pos] as u32 / 3
                            })
                            .map(|g| g.pos)
                    })
                    .unwrap_or(p)
            };
            let cost = |q: usize| {
                if s.carry[v] {
                    self.home[team][q]
                } else {
                    b.distance(q, goal)
                }
            };
            let mut best = cost(p);
            for &q in &b.adj[p] {
                if q == NONE || s.carry[v] && s.ground[q] > 0 {
                    continue;
                }
                if cost(q) < best {
                    best = cost(q);
                    *destination = q;
                }
            }
        }
        next
    }
    fn rollout(
        &self,
        mut s: State,
        goals: &[Goal],
        mine: &[usize; 3],
        assigned: &[usize; 3],
    ) -> f32 {
        let b = self.board.as_ref().unwrap();
        let mut value = 0.;
        let depth = if self.home.len() <= 5 { 3 } else { 1 };
        for step in 0..depth {
            let discount = [0.48, 0.26, 0.13][step];
            let shots: Vec<_> = (0..self.home.len())
                .map(|t| volley(b, &s, t as u32))
                .collect();
            let desired = self.predicted_moves(&s, &shots, goals, mine, assigned);
            let mut damage = [0; 24];
            for shot in &shots {
                for (e, hit) in damage.iter_mut().enumerate().take(s.count) {
                    *hit += shot.hits[e];
                }
            }
            value += discount * 0.85 * shots[self.team].value;
            for &v in mine {
                if v == NONE || s.pos[v] == NONE {
                    continue;
                }
                let hits = damage[v].min(s.hp[v]) as f32;
                value -= discount * hits * if s.carry[v] { 6.5 } else { 3.2 };
                if damage[v] >= s.hp[v] {
                    value -= discount * if s.carry[v] { 38. } else { 12.5 };
                }
            }
            let old = s.pos;
            let carried = s.carry;
            s.damage(&damage);
            s.movement(&desired);
            let (_, delivered) = s.collect(&self.home);
            for &v in mine {
                if v == NONE || s.pos[v] == NONE {
                    continue;
                }
                if carried[v] {
                    value += discount
                        * 0.9
                        * (self.home[self.team][old[v]] as f32
                            - self.home[self.team][s.pos[v]] as f32);
                }
            }
            for (v, &yes) in delivered.iter().enumerate().take(s.count) {
                if yes {
                    value += discount
                        * if s.team[v] as usize == self.team {
                            22.
                        } else {
                            -5.
                        };
                }
            }
        }
        value
    }
    pub fn search(
        &mut self,
        v: &ObservationView<'_>,
        s: &State,
        goals: &[Goal],
        mine: &[usize; 3],
        assigned: &[usize; 3],
    ) -> CtfTeamAction {
        let b = self.board.as_ref().unwrap();
        let shots: Vec<_> = (0..self.home.len())
            .map(|t| volley(b, s, t as u32))
            .collect();
        let epred = self.predicted_moves(s, &shots, goals, mine, assigned);
        let mut third = [0; 24];
        for (t, shot) in shots.iter().enumerate() {
            if t != self.team {
                for (e, h) in third.iter_mut().enumerate().take(s.count) {
                    *h += shot.hits[e];
                }
            }
        }
        let enemies: Vec<_> = (0..s.count)
            .filter(|&e| s.team[e] as usize != self.team && s.pos[e] != NONE)
            .collect();
        // Enemy targeting is unknown. A carrier must not rely on a forecast
        // choosing one low-health carrier over another before movement.
        let mut blocked_ground = s.ground.clone();
        for e in 0..s.count {
            if s.pos[e] == NONE || !s.carry[e] {
                continue;
            }
            let possible_hits = (0..s.count)
                .filter(|&z| {
                    s.pos[z] != NONE
                        && !s.carry[z]
                        && s.team[z] != s.team[e]
                        && b.sight(s.pos[z], s.pos[e])
                })
                .count();
            if possible_hits >= s.hp[e] as usize {
                blocked_ground[s.pos[e]] = 1;
            }
        }
        let mut options: [Vec<OptionMove>; 3] = std::array::from_fn(|_| vec![]);
        for i in 0..3 {
            let u = mine[i];
            if u == NONE || s.pos[u] == NONE {
                options[i].push(OptionMove {
                    kind: WAIT,
                    dir: 0,
                    pos: NONE,
                    target: NONE,
                    base: 0.,
                });
                continue;
            }
            let p = s.pos[u];
            let carrying = s.carry[u];
            let mut risk = vec![0.; b.n];
            for (q, r) in risk.iter_mut().enumerate() {
                if b.walls[q] != 0 {
                    continue;
                }
                for &e in &enemies {
                    if !s.carry[e] {
                        if b.sight(s.pos[e], q) {
                            *r += if carrying { 1.5 } else { 0.10 };
                        } else if b.sight(epred[e], q) {
                            *r += if carrying { 1.1 } else { 0.08 };
                        }
                    }
                }
            }
            let destinations: Vec<_> = if carrying {
                self.home[self.team]
                    .iter()
                    .enumerate()
                    .filter_map(|(p, &d)| (d == 0).then_some(p))
                    .collect()
            } else {
                vec![goals[assigned[i]].pos]
            };
            let path = route(b, &destinations, &blocked_ground, &risk, carrying);
            let base = |q: usize| {
                let progress =
                    (path[p] - path[q] - if q != p { risk[q] } else { 0. }).clamp(-10., 10.);
                let mut value = progress * if carrying { 2.6 } else { 1.0 };
                if q == p {
                    value -= 0.14;
                }
                if carrying && self.home[self.team][q] == 0 {
                    value += 22.;
                }
                if !carrying && s.ground[q] > 0 {
                    value += 5.;
                }
                if q != p && self.last_pos[i] == q {
                    value -= 0.25;
                }
                value
            };
            options[i].push(OptionMove {
                kind: WAIT,
                dir: 0,
                pos: p,
                target: NONE,
                base: base(p),
            });
            for (dir, &q) in b.adj[p].iter().enumerate() {
                if q != NONE && (!carrying || blocked_ground[q] == 0) {
                    options[i].push(OptionMove {
                        kind: MOVE,
                        dir: dir as u32,
                        pos: q,
                        target: NONE,
                        base: base(q),
                    });
                }
            }
            if !carrying {
                let mut targets: Vec<_> = enemies
                    .iter()
                    .copied()
                    .filter(|&e| b.sight(p, s.pos[e]))
                    .collect();
                targets.sort_by(|&a, &c| {
                    let priority = |e: usize| 3. * s.carry[e] as u32 as f32 + 2. / s.hp[e] as f32;
                    priority(c).total_cmp(&priority(a))
                });
                targets.truncate(6);
                for e in targets {
                    options[i].push(OptionMove {
                        kind: SHOOT,
                        dir: 0,
                        pos: p,
                        target: e,
                        base: base(p),
                    });
                }
            }
        }
        let mut beam = Vec::with_capacity(1331);
        for a in 0..options[0].len() {
            for c in 0..options[1].len() {
                for d in 0..options[2].len() {
                    let choice = [a, c, d];
                    let chosen = [options[0][a], options[1][c], options[2][d]];
                    let mut damage = [0; 24];
                    for op in chosen {
                        if op.target != NONE {
                            damage[op.target] += 1;
                        }
                    }
                    let mut value = chosen.iter().map(|o| o.base).sum::<f32>();
                    let mut valid = true;
                    for i in 0..3 {
                        let p = chosen[i].pos;
                        if p == NONE {
                            continue;
                        }
                        for op in chosen.iter().take(i) {
                            if op.pos == p {
                                valid = false;
                            }
                        }
                        if let Some(e) = enemies.iter().find(|&&e| s.pos[e] == p)
                            && damage[*e] + third[*e] < s.hp[*e]
                            && epred[*e] == s.pos[*e]
                        {
                            valid = false;
                        }
                    }
                    if !valid {
                        continue;
                    }
                    for &e in &enemies {
                        let remaining = s.hp[e].saturating_sub(third[e]);
                        let hits = remaining.min(damage[e]);
                        value += hits as f32 * (2.5 + 1.8 * s.carry[e] as u32 as f32);
                        if remaining > 0 && hits == remaining {
                            value += 6. + 11. * s.carry[e] as u32 as f32;
                        }
                        value -= damage[e].saturating_sub(remaining) as f32 * 1.5;
                    }
                    let immediate = value;
                    for i in 0..3 {
                        let u = mine[i];
                        let p = chosen[i].pos;
                        if u == NONE || p == NONE {
                            continue;
                        }
                        let hp = s.hp[u].saturating_sub(third[u]);
                        if hp == 0 {
                            if chosen[i].kind != SHOOT {
                                value -= chosen[i].base;
                            }
                            continue;
                        }
                        let mut expected = 0.;
                        let weight = 1. + 2.5 * s.carry[u] as u32 as f32 + 1. / (hp as f32 + 0.5);
                        for &e in &enemies {
                            if s.carry[e] || damage[e] + third[e] >= s.hp[e] {
                                continue;
                            }
                            let exposure = if b.sight(p, epred[e]) {
                                0.9
                            } else if b.sight(p, s.pos[e]) {
                                0.5
                            } else {
                                0.
                            };
                            if exposure == 0. {
                                continue;
                            }
                            let mut total = weight;
                            for j in 0..3 {
                                if i != j
                                    && chosen[j].pos != NONE
                                    && b.sight(chosen[j].pos, epred[e])
                                {
                                    total += 1.
                                        + 2.5 * s.carry[mine[j]] as u32 as f32
                                        + 1. / (s.hp[mine[j]] as f32 + 0.5);
                                }
                            }
                            for &z in &enemies {
                                if s.team[z] != s.team[e] && b.sight(epred[z], epred[e]) {
                                    total += 1.2;
                                }
                            }
                            expected += exposure * weight / total;
                        }
                        value -= expected * if s.carry[u] { 3.6 } else { 1.4 };
                        value -= ((expected - hp as f32 + 0.65) / 0.8).clamp(0., 1.)
                            * if s.carry[u] { 16. } else { 6. };
                    }
                    beam.push((value, immediate, choice));
                }
            }
        }
        beam.sort_unstable_by(|a, c| c.0.total_cmp(&a.0));
        beam.truncate(20);
        let mut best = -1e30;
        let mut selected = [0; 3];
        for (_, immediate, choice) in beam {
            let mut after = s.clone();
            let mut damage = third;
            let mut desired = epred;
            for i in 0..3 {
                let op = options[i][choice[i]];
                if op.target != NONE {
                    damage[op.target] += 1;
                }
                if mine[i] != NONE {
                    desired[mine[i]] = op.pos;
                }
            }
            after.damage(&damage);
            after.movement(&desired);
            let (picked, delivered) = after.collect(&self.home);
            let mut value = immediate;
            for i in 0..3 {
                let u = mine[i];
                if u == NONE {
                    continue;
                }
                let op = options[i][choice[i]];
                if after.pos[u] == NONE {
                    if op.kind != SHOOT {
                        value -= op.base;
                    }
                    continue;
                }
                if after.pos[u] != op.pos {
                    value -= op.base - options[i][0].base;
                }
                if picked[u] && s.ground[after.pos[u]] == 0 {
                    value += 5.;
                }
                if delivered[u] && !s.carry[u] {
                    value += 22.;
                }
            }
            value += self.rollout(after, goals, mine, assigned);
            if value > best {
                best = value;
                selected = choice;
            }
        }
        let mut out = CtfTeamAction::waits();
        for i in 0..3 {
            let op = options[i][selected[i]];
            let a = &mut out.actions[i];
            a.kind = op.kind;
            a.direction = op.dir;
            if op.target != NONE {
                a.target_x = v.units[op.target].x;
                a.target_y = v.units[op.target].y;
            }
            self.last_pos[i] = if mine[i] != NONE {
                s.pos[mine[i]]
            } else {
                NONE
            };
            self.last_goal[i] = goals[assigned[i]].pos;
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn forecast_chases_flags_remaining_after_collection() {
        let mut bot = Bot::new(5, 15);
        bot.board = Some(Board::new(9, 9, &[0; 81]));
        bot.team = 0;
        bot.home = vec![vec![10; 81]; 2];
        let mut s = State {
            pos: [NONE; 24],
            hp: [0; 24],
            carry: [false; 24],
            team: [0; 24],
            count: 6,
            ground: vec![0; 81],
        };
        s.team[3..6].fill(1);
        s.pos[3] = 40;
        s.hp[3] = 3;
        s.ground[41] = 1;
        bot.board.as_mut().unwrap().ensure(41);
        bot.board.as_mut().unwrap().ensure(31);
        let shots = vec![
            Volley {
                hits: [0; 24],
                target: [NONE; 3],
                value: 0.
            };
            2
        ];
        let stale = [Goal {
            pos: 31,
            wait: 0.,
            ground: true,
        }];
        let predicted = bot.predicted_moves(&s, &shots, &stale, &[0, 1, 2], &[0; 3]);
        assert_eq!(predicted[3], 41);
    }
}
