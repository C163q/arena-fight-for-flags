use crate::*;
use serde_json::json;
use std::cmp::Ordering;

// Closed cell boxes in doubled integer coordinates; rational slab intersections
// include corner touches without floating point rounding or platform differences.
pub fn line_cells(from: Point, to: Point) -> Vec<Point> {
    fn cmp(a: (i64, i64), b: (i64, i64)) -> Ordering {
        (a.0 * b.1).cmp(&(b.0 * a.1))
    }
    let mut cells = Vec::new();
    for y in from.y.min(to.y)..=from.y.max(to.y) {
        for x in from.x.min(to.x)..=from.x.max(to.x) {
            let mut lo = (0, 1);
            let mut hi = (1, 1);
            let mut hit = true;
            for (start, end, cell) in [(from.x, to.x, x), (from.y, to.y, y)] {
                let origin = 2 * i64::from(start);
                let delta = 2 * (i64::from(end) - i64::from(start));
                let left = 2 * i64::from(cell) - 1;
                let right = left + 2;
                if delta == 0 {
                    if origin < left || origin > right {
                        hit = false;
                        break;
                    }
                    continue;
                }
                let (a, b) = if delta > 0 {
                    ((left - origin, delta), (right - origin, delta))
                } else {
                    ((origin - right, -delta), (origin - left, -delta))
                };
                if cmp(a, lo).is_gt() {
                    lo = a;
                }
                if cmp(b, hi).is_lt() {
                    hi = b;
                }
                if cmp(lo, hi).is_gt() {
                    hit = false;
                    break;
                }
            }
            if hit {
                cells.push((lo, Point::new(x, y)));
            }
        }
    }
    cells.sort_by(|a, b| {
        cmp(a.0, b.0)
            .then(a.1.y.cmp(&b.1.y))
            .then(a.1.x.cmp(&b.1.x))
    });
    cells.into_iter().map(|(_, p)| p).collect()
}
pub(crate) fn resolve(e: &mut Engine, actions: &mut [TeamActions]) {
    let before = e.state.units.clone();
    let mut sources = vec![Vec::<String>::new(); before.len()];
    for (i, u) in before.iter().enumerate() {
        let Action::Shoot { target } = actions[i / 3][i % 3] else {
            continue;
        };
        let validation = if u.position.is_none() {
            "dead_unit"
        } else if u.carrying.is_some() {
            "carrying_cannot_shoot"
        } else if !e.map.contains(target) {
            "out_of_bounds"
        } else if u.position == Some(target) {
            "self_target"
        } else {
            let p = u.position.expect("live");
            if (i64::from(p.x) - i64::from(target.x)).abs()
                + (i64::from(p.y) - i64::from(target.y)).abs()
                > i64::from(RANGE)
            {
                "out_of_range"
            } else {
                "ok"
            }
        };
        if validation != "ok" {
            actions[i / 3][i % 3] = Action::Wait;
            e.emit("shoot","shot",json!({"shooter":u.id,"from":u.position,"target":target,"validation":validation,"result":"not_executed","hit_unit":null,"damage":0,"line_cells":[]}));
            continue;
        }
        let from = u.position.expect("live");
        let line = line_cells(from, target);
        let blocked = line
            .iter()
            .copied()
            .find(|&p| p != from && !e.map.is_walkable(p));
        let victim = if blocked.is_none() {
            before.iter().position(|u| u.position == Some(target))
        } else {
            None
        };
        let event=e.emit("shoot","shot",json!({"shooter":u.id,"from":from,"target":target,"range_distance":(from.x-target.x).abs()+(from.y-target.y).abs(),"validation":"ok","result":if blocked.is_some(){"blocked"}else if victim.is_some(){"hit"}else{"miss"},"hit_unit":victim.map(|i|before[i].id),"damage":if victim.is_some(){1}else{0},"blocked_by":blocked,"line_cells":line}));
        if let Some(j) = victim {
            sources[j].push(event);
        }
    }
    let mut deaths = Vec::new();
    for (i, hits) in sources.into_iter().enumerate() {
        if hits.is_empty() {
            continue;
        }
        let old = e.state.units[i].hp;
        let damage = hits.len() as u32;
        let new = u32::from(old).saturating_sub(damage) as u8;
        e.state.units[i].hp = new;
        let source = e.emit(
            "shoot",
            "hp_change",
            json!({"unit":before[i].id,"before":old,"after":new,"damage":damage,"sources":hits}),
        );
        if new == 0 {
            deaths.push((i, source));
        }
    }
    for (i, source) in deaths {
        let id = before[i].id;
        let position = e.state.units[i].position.take().expect("shot living unit");
        e.state.units[i].respawn_at_turn = Some(e.state.turn + RESPAWN_ABSENT_TURNS + 1);
        let death=e.emit("shoot","death",json!({"unit":id,"position":position,"source":source,"respawn_at_turn":e.state.turn+RESPAWN_ABSENT_TURNS+1}));
        if let Some(flag_id) = e.state.units[i].carrying.take() {
            e.state
                .flags
                .iter_mut()
                .find(|f| f.id == flag_id)
                .expect("validated flag")
                .location = FlagLocation::Ground { position };
            e.emit("shoot","carry_change",json!({"unit":id,"before":flag_id,"after":null,"reason":"death_drop","flag_id":flag_id,"ground":position,"source":death}));
        }
    }
}
