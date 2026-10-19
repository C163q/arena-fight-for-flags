use crate::{
    Bot,
    board::{Board, FAR, NONE},
    forecast::State,
};
use fff_ai_abi::*;
use std::{cmp::Reverse, collections::BinaryHeap};

#[derive(Clone, Copy)]
pub struct Goal {
    pub pos: usize,
    pub wait: f32,
    pub ground: bool,
}
#[derive(Default)]
pub struct SiteMemory {
    pub active: bool,
    pub removed: u32,
}

impl Bot {
    pub fn goals(&mut self, v: &ObservationView<'_>, s: &State) -> Vec<Goal> {
        let b = self.board.as_ref().unwrap();
        let mut goals = Vec::new();
        for f in v.flags.iter().filter(|f| f.state == 0) {
            if let Some(p) = b.cell(f.x, f.y) {
                goals.push(Goal {
                    pos: p,
                    wait: 0.,
                    ground: true,
                });
            }
        }
        if self.sites.len() != v.sites.len() {
            self.sites = (0..v.sites.len()).map(|_| SiteMemory::default()).collect();
        }
        let regen = (self.min_wait as f32 + self.max_wait as f32) * 0.5;
        for (i, site) in v.sites.iter().enumerate() {
            let Some(p) = b.cell(site.x, site.y) else {
                continue;
            };
            let active = v.flags.iter().find(|f| f.site_id == site.id);
            let mem = &mut self.sites[i];
            if mem.active && active.is_none() {
                mem.removed = v.meta.turn.saturating_sub(1);
            }
            mem.active = active.is_some();
            let wait = if let Some(flag) = active {
                if flag.state == 0 {
                    continue;
                }
                let carrier = v
                    .units
                    .iter()
                    .position(|u| u.team_id == flag.carrier_team && u.unit_id == flag.carrier_unit);
                if let Some(e) = carrier.filter(|&e| s.pos[e] != NONE) {
                    self.home[flag.carrier_team as usize][s.pos[e]] as f32 + regen
                } else {
                    regen + 10.
                }
            } else {
                let age = v.meta.turn.saturating_sub(1).saturating_sub(mem.removed);
                let low = self.min_wait.max(age.min(self.max_wait));
                ((low as f32 + self.max_wait as f32) * 0.5 - age as f32).max(0.)
            };
            goals.push(Goal {
                pos: p,
                wait,
                ground: false,
            });
        }
        if goals.is_empty() {
            for site in v.sites {
                if let Some(pos) = b.cell(site.x, site.y) {
                    goals.push(Goal {
                        pos,
                        wait: 20.,
                        ground: false,
                    });
                }
            }
        }
        goals
    }
    pub fn assign(
        &self,
        v: &ObservationView<'_>,
        s: &State,
        goals: &[Goal],
        mine: &[usize; 3],
    ) -> [usize; 3] {
        let b = self.board.as_ref().unwrap();
        let team = v.meta.team_id as usize;
        let mut costs = vec![vec![0.; goals.len()]; 3];
        let mut choices: [Vec<usize>; 3] = std::array::from_fn(|_| vec![]);
        for i in 0..3 {
            let u = mine[i];
            if u == NONE || s.pos[u] == NONE || s.carry[u] {
                choices[i].push(0);
                continue;
            }
            for (g, goal) in goals.iter().enumerate() {
                let d = b.distance(s.pos[u], goal.pos) as f32;
                let ed = (0..s.count)
                    .filter(|&e| s.team[e] != team as u32 && s.pos[e] != NONE && !s.carry[e])
                    .map(|e| b.distance(s.pos[e], goal.pos))
                    .min()
                    .unwrap_or(FAR) as f32;
                let back = self.home[team][goal.pos] as f32;
                // With three to five teams, a short return route is usually
                // worth more than arriving slightly earlier at a distant flag.
                let local = (3..=5).contains(&v.meta.team_count);
                let mut cost = d + if local { 0.85 } else { 0.38 } * back;
                cost += (d - ed).max(0.) * if local { 1.5 } else { 0.7 };
                if goal.ground {
                    cost -= if local { 1.0 } else { 7.0 };
                } else {
                    cost += (goal.wait - d).max(0.) * if local { 1.0 } else { 0.5 } + 1.0;
                }
                // Avoid oscillating goals without making a previous bad choice permanent.
                if self.last_goal[i] == goal.pos {
                    cost -= 0.6;
                }
                let guards = (0..s.count)
                    .filter(|&e| {
                        s.team[e] != team as u32
                            && s.pos[e] != NONE
                            && !s.carry[e]
                            && b.sight(s.pos[e], goal.pos)
                    })
                    .count();
                cost += guards.saturating_sub(1) as f32 * 0.8;
                costs[i][g] = cost;
                choices[i].push(g);
            }
            choices[i].sort_by(|&a, &c| costs[i][a].total_cmp(&costs[i][c]));
            choices[i].truncate(8);
        }
        let mut best = f32::INFINITY;
        let mut assigned = [0; 3];
        for &a in &choices[0] {
            for &c in &choices[1] {
                for &d in &choices[2] {
                    let gs = [a, c, d];
                    let mut value = 0.;
                    for i in 0..3 {
                        value += costs[i][gs[i]];
                        for j in 0..i {
                            let u = mine[i];
                            let z = mine[j];
                            if u != NONE
                                && z != NONE
                                && s.pos[u] != NONE
                                && s.pos[z] != NONE
                                && !s.carry[u]
                                && !s.carry[z]
                                && gs[i] == gs[j]
                            {
                                value += if goals[gs[i]].ground { 11. } else { 7. };
                            }
                        }
                    }
                    if value < best {
                        best = value;
                        assigned = gs;
                    }
                }
            }
        }
        assigned
    }
}

pub fn route(b: &Board, goals: &[usize], ground: &[u8], risk: &[f32], carrier: bool) -> Vec<f32> {
    let mut dist = vec![u32::MAX / 4; b.n];
    let mut heap = BinaryHeap::new();
    for &p in goals {
        if p < b.n && (!carrier || ground[p] == 0) {
            dist[p] = 0;
            heap.push(Reverse((0, p)));
        }
    }
    while let Some(Reverse((d, p))) = heap.pop() {
        if d != dist[p] {
            continue;
        }
        if carrier && ground[p] > 0 {
            continue;
        }
        let step = 100 + (risk[p] * 100.) as u32;
        for &q in &b.adj[p] {
            if q != NONE && d + step < dist[q] {
                dist[q] = d + step;
                heap.push(Reverse((d + step, q)));
            }
        }
    }
    dist.into_iter().map(|d| d as f32 / 100.).collect()
}
