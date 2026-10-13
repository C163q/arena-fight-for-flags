use fff_ai_abi::*;
use std::collections::{BTreeSet, VecDeque};
type Pos = (i32, i32);
const STEPS: [(i32, i32, u32); 4] = [(0, -1, UP), (0, 1, DOWN), (-1, 0, LEFT), (1, 0, RIGHT)];
pub fn greedy(view: &ObservationView<'_>) -> CtfTeamAction {
    decide(view, false)
}
pub fn baseline(view: &ObservationView<'_>) -> CtfTeamAction {
    decide(view, true)
}
fn walkable(v: &ObservationView<'_>, p: Pos) -> bool {
    p.0 >= 0
        && p.1 >= 0
        && (p.0 as u32) < v.meta.width
        && (p.1 as u32) < v.meta.height
        && v.cells[p.1 as usize * v.meta.width as usize + p.0 as usize] == 0
}
fn index(v: &ObservationView<'_>, p: Pos) -> usize {
    p.1 as usize * v.meta.width as usize + p.0 as usize
}
fn clear_line(v: &ObservationView<'_>, from: Pos, to: Pos) -> bool {
    if !walkable(v, from) || !walkable(v, to) {
        return false;
    }
    for y in from.1.min(to.1)..=from.1.max(to.1) {
        for x in from.0.min(to.0)..=from.0.max(to.0) {
            if walkable(v, (x, y)) {
                continue;
            }
            let mut lo = (0i64, 1i64);
            let mut hi = (1i64, 1i64);
            let mut hit = true;
            for (a, b, c) in [(from.0, to.0, x), (from.1, to.1, y)] {
                let o = 2 * i64::from(a);
                let d = 2 * (i64::from(b) - i64::from(a));
                let l = 2 * i64::from(c) - 1;
                let r = l + 2;
                if d == 0 {
                    if o < l || o > r {
                        hit = false;
                        break;
                    }
                    continue;
                }
                let (low, high) = if d > 0 {
                    ((l - o, d), (r - o, d))
                } else {
                    ((o - r, -d), (o - l, -d))
                };
                if low.0 * lo.1 > lo.0 * low.1 {
                    lo = low;
                }
                if high.0 * hi.1 < hi.0 * high.1 {
                    hi = high;
                }
                if lo.0 * hi.1 > hi.0 * lo.1 {
                    hit = false;
                    break;
                }
            }
            if hit {
                return false;
            }
        }
    }
    true
}
fn routes(
    v: &ObservationView<'_>,
    start: Pos,
    blocked: &BTreeSet<Pos>,
) -> (Vec<u32>, Vec<Option<u32>>) {
    let len = v.cells.len();
    let mut distances = vec![u32::MAX; len];
    let mut first = vec![None; len];
    if !walkable(v, start) {
        return (distances, first);
    }
    let mut queue = VecDeque::from([start]);
    distances[index(v, start)] = 0;
    while let Some(p) = queue.pop_front() {
        for (dx, dy, direction) in STEPS {
            let next = (p.0 + dx, p.1 + dy);
            if !walkable(v, next) || blocked.contains(&next) {
                continue;
            }
            let ni = index(v, next);
            if distances[ni] != u32::MAX {
                continue;
            }
            distances[ni] = distances[index(v, p)] + 1;
            first[ni] = if p == start {
                Some(direction)
            } else {
                first[index(v, p)]
            };
            queue.push_back(next);
        }
    }
    (distances, first)
}
fn decide(v: &ObservationView<'_>, smart: bool) -> CtfTeamAction {
    let mut output = CtfTeamAction::waits();
    let team = v.meta.team_id;
    let mut order: Vec<_> = v
        .units
        .iter()
        .filter(|u| u.team_id == team && u.alive != 0)
        .collect();
    order.sort_by_key(|u| (u.carrying == 0, u.unit_id));
    let mut reserved = BTreeSet::new();
    let mut assigned = Vec::<Pos>::new();
    let mut planned_hits = vec![0u32; v.units.len()];
    for u in order {
        let from = (u.x, u.y);
        let slot = u.unit_id as usize;
        if slot >= 3 || !walkable(v, from) {
            continue;
        }
        if smart && u.carrying == 0 {
            let target = v
                .units
                .iter()
                .enumerate()
                .filter(|(i, t)| {
                    t.alive != 0
                        && t.team_id != team
                        && planned_hits[*i] < t.hp
                        && u.x.abs_diff(t.x) + u.y.abs_diff(t.y) <= 5
                        && clear_line(v, from, (t.x, t.y))
                })
                .max_by_key(|(_, t)| {
                    (if t.carrying != 0 { 100 } else { 0 }) + 20 - (t.hp as i32) * 3
                });
            if let Some((i, t)) = target {
                output.actions[slot] = CtfAction {
                    unit_id: u.unit_id,
                    kind: SHOOT,
                    target_x: t.x,
                    target_y: t.y,
                    direction: 0,
                };
                planned_hits[i] += 1;
                reserved.insert(from);
                continue;
            }
        }
        let mut blocked = reserved.clone();
        for other in v.units.iter().filter(|t| {
            t.alive != 0
                && (t.team_id != team || !smart)
                && !(t.team_id == team && t.unit_id == u.unit_id)
        }) {
            blocked.insert((other.x, other.y));
        }
        if u.carrying != 0 {
            for flag in v.flags.iter().filter(|f| f.state == 0) {
                blocked.insert((flag.x, flag.y));
            }
        }
        let (distance, first) = routes(v, from, &blocked);
        let mut goals = Vec::<(Pos, i32)>::new();
        if u.carrying != 0 {
            if let Some(home) = v.homes.iter().find(|h| h.team_id == team) {
                for y in home.y..home.y + home.height as i32 {
                    for x in home.x..home.x + home.width as i32 {
                        goals.push(((x, y), 2000));
                    }
                }
            }
        } else {
            for flag in v.flags.iter().filter(|f| f.state == 0) {
                goals.push(((flag.x, flag.y), 1000));
            }
            if goals.is_empty() {
                for site in v.sites {
                    if smart && v.flags.iter().any(|f| f.site_id == site.id) {
                        continue;
                    }
                    goals.push(((site.x, site.y), 500));
                }
            }
        }
        let best = goals
            .into_iter()
            .filter(|(p, _)| walkable(v, *p) && distance[index(v, *p)] != u32::MAX)
            .max_by_key(|(p, value)| {
                *value
                    - distance[index(v, *p)] as i32 * 12
                    - if smart {
                        assigned.iter().filter(|&&q| q == *p).count() as i32 * 100
                    } else {
                        0
                    }
            });
        if let Some((goal, _)) = best {
            assigned.push(goal);
            if let Some(direction) = first[index(v, goal)] {
                let &(dx, dy, _) = STEPS
                    .iter()
                    .find(|s| s.2 == direction)
                    .expect("route direction");
                let destination = (from.0 + dx, from.1 + dy);
                output.actions[slot] = CtfAction {
                    unit_id: u.unit_id,
                    kind: MOVE,
                    direction,
                    target_x: 0,
                    target_y: 0,
                };
                reserved.insert(destination);
                continue;
            }
        }
        reserved.insert(from);
    }
    if smart {
        // Cancel chains ending at a teammate that ultimately waits or shoots.
        loop {
            let mut cancel = Vec::new();
            for u in v.units.iter().filter(|u| u.team_id == team && u.alive != 0) {
                let action = output.actions[u.unit_id as usize];
                if action.kind != MOVE {
                    continue;
                }
                let &(dx, dy, _) = STEPS
                    .iter()
                    .find(|s| s.2 == action.direction)
                    .expect("move direction");
                if v.units.iter().any(|t| {
                    t.alive != 0
                        && t.team_id == team
                        && (t.x, t.y) == (u.x + dx, u.y + dy)
                        && output.actions[t.unit_id as usize].kind != MOVE
                }) {
                    cancel.push(u.unit_id as usize);
                }
            }
            if cancel.is_empty() {
                break;
            }
            for i in cancel {
                output.actions[i] = CtfAction {
                    unit_id: i as u32,
                    ..CtfAction::default()
                };
            }
        }
    }
    output
}
