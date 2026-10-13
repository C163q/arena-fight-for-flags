use crate::*;
use serde_json::json;
use std::collections::BTreeMap;

pub(crate) fn resolve(e: &mut Engine, actions: &mut [TeamActions], start: &Snapshot) {
    let original = actions.to_vec();
    let before = e.state.units.clone();
    let n = before.len();
    let mut targets = vec![None; n];
    let mut reasons = vec!["ok"; n];
    for (i, u) in before.iter().enumerate() {
        let Action::Move { direction } = actions[i / 3][i % 3] else {
            continue;
        };
        let Some(from) = u.position else {
            reasons[i] = if start.units[i].position.is_some() {
                "killed_before_move"
            } else {
                "dead_unit"
            };
            actions[i / 3][i % 3] = Action::Wait;
            continue;
        };
        let (dx, dy) = match direction {
            Direction::Up => (0, -1),
            Direction::Down => (0, 1),
            Direction::Left => (-1, 0),
            Direction::Right => (1, 0),
        };
        let target = Point::new(from.x + dx, from.y + dy);
        reasons[i] = if !e.map.contains(target) {
            "out_of_bounds"
        } else if !e.map.is_walkable(target) {
            "obstacle"
        } else if u.carrying.is_some()
            && e.state
                .flags
                .iter()
                .any(|f| f.location == FlagLocation::Ground { position: target })
        {
            "carrying_cannot_enter_flag"
        } else {
            "ok"
        };
        if reasons[i] == "ok" {
            targets[i] = Some(target);
        } else {
            actions[i / 3][i % 3] = Action::Wait;
        }
    }
    let mut contenders = BTreeMap::<Point, Vec<usize>>::new();
    for (i, p) in targets.iter().enumerate() {
        if let Some(p) = p {
            contenders.entry(*p).or_default().push(i);
        }
    }
    for group in contenders.values().filter(|g| g.len() > 1) {
        for &i in group {
            targets[i] = None;
            reasons[i] = "contested";
        }
    }
    let mut success = vec![false; n];
    for i in 0..n {
        if targets[i].is_none() {
            continue;
        }
        let mut path = Vec::<usize>::new();
        let mut at = i;
        let good = loop {
            if let Some(cycle_start) = path.iter().position(|&j| j == at) {
                let team = before[at].id.team_id;
                break path[cycle_start..]
                    .iter()
                    .all(|&j| before[j].id.team_id == team);
            }
            path.push(at);
            let Some(target) = targets[at] else {
                break false;
            };
            match before.iter().position(|u| u.position == Some(target)) {
                None => break true,
                Some(next) => at = next,
            }
        };
        success[i] = good;
    }
    for i in 0..n {
        if success[i] {
            e.state.units[i].position = targets[i];
        }
    }
    for (i, u) in before.iter().enumerate() {
        // Preserve original move submissions even when the legal action became Wait.
        let Action::Move { direction: raw } = original[i / 3][i % 3] else {
            continue;
        };
        let target = start.units[i].position.map(|p| {
            let (dx, dy) = match raw {
                Direction::Up => (0, -1),
                Direction::Down => (0, 1),
                Direction::Left => (-1, 0),
                Direction::Right => (1, 0),
            };
            Point::new(p.x + dx, p.y + dy)
        });
        let flags: Vec<_> = e
            .state
            .flags
            .iter()
            .filter_map(|f| match f.location {
                FlagLocation::Ground { position } if Some(position) == target => Some(f.id),
                _ => None,
            })
            .collect();
        e.emit("move","move",json!({"unit":u.id,"from":start.units[i].position,"target":target,"validation":if matches!(reasons[i],"ok"|"contested"|"killed_before_move"){"ok"}else{reasons[i]},"result":if success[i]{"moved"}else if reasons[i]=="killed_before_move"{"cancelled"}else if matches!(reasons[i],"ok"|"contested"){"blocked"}else{"not_executed"},"reason":if !success[i]&&reasons[i]=="ok"{"occupied_or_cycle"}else{reasons[i]},"final_position":e.state.units[i].position,"carrying":u.carrying,"target_flags":flags}));
    }
}
