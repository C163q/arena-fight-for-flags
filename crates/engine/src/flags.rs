use crate::*;
use serde_json::json;

pub(crate) fn spawn(e: &mut Engine, site_index: usize, phase: &str) {
    let site_id = e.state.sites[site_index].site_id;
    let point = &e.map.flag_points[site_index];
    let p = Point::new(point.x as i32, point.y as i32);
    let occupant = e.occupied(p);
    let flag_id = e.state.next_flag_id;
    e.state.next_flag_id += 1;
    let schedule = e.state.sites[site_index].scheduled_by.clone();
    e.state.sites[site_index].active_flag_id = Some(flag_id);
    e.state.sites[site_index].next_attempt_turn = None;
    e.state.sites[site_index].scheduled_by = None;
    e.state.flags.push(Flag {
        id: flag_id,
        site_id,
        location: FlagLocation::Ground { position: p },
    });
    let source=e.emit(phase,"flag_spawned",json!({"flag_id":flag_id,"site_id":site_id,"position":p,"schedule":schedule,"reason":if phase=="initial"{"initial_immediate"}else{"scheduled"}}));
    if let Some(i) = occupant {
        debug_assert!(e.state.units[i].carrying.is_none());
        take(e, i, flag_id, phase, "spawn_pickup", Some(source));
    }
}
fn take(e: &mut Engine, i: usize, id: u64, phase: &str, reason: &str, source: Option<String>) {
    let unit = e.state.units[i].id;
    e.state.units[i].carrying = Some(id);
    e.state
        .flags
        .iter_mut()
        .find(|f| f.id == id)
        .expect("existing flag")
        .location = FlagLocation::Carried { unit };
    e.emit(
        phase,
        "carry_change",
        json!({"unit":unit,"before":null,"after":id,"reason":reason,"flag_id":id,"source":source}),
    );
}
pub(crate) fn pickup_existing(e: &mut Engine) {
    for i in 0..e.state.units.len() {
        if e.state.units[i].carrying.is_some() {
            continue;
        }
        let Some(p) = e.state.units[i].position else {
            continue;
        };
        if let Some(id) = e
            .state
            .flags
            .iter()
            .filter_map(|f| (f.location == FlagLocation::Ground { position: p }).then_some(f.id))
            .min()
        {
            take(e, i, id, "pickup", "ground_pickup", None);
        }
    }
}
fn schedule(e: &mut Engine, index: usize, reason: &str, source: String) {
    let delay = e.delay();
    let next = e.state.turn + delay;
    let site_id = e.state.sites[index].site_id;
    let origin = e.state.sites[index].origin.clone();
    let phase = if reason == "after_return" {
        "score"
    } else {
        "flag_spawn"
    };
    let event=e.emit(phase,"flag_respawn_scheduled",json!({"site_id":site_id,"reason":reason,"origin":origin,"source":source,"delay":delay,"next_attempt_turn":next,"next_attempt_phase":"flag_spawn"}));
    let s = &mut e.state.sites[index];
    s.next_attempt_turn = Some(next);
    s.scheduled_by = Some(event);
}
pub(crate) fn generate_due(e: &mut Engine) {
    for i in 0..e.state.sites.len() {
        if e.state.sites[i].active_flag_id.is_some()
            || e.state.sites[i]
                .next_attempt_turn
                .is_none_or(|t| t > e.state.turn)
        {
            continue;
        }
        let site_id = e.state.sites[i].site_id;
        let point = &e.map.flag_points[i];
        let p = Point::new(point.x as i32, point.y as i32);
        if let Some(j) = e
            .occupied(p)
            .filter(|&j| e.state.units[j].carrying.is_some())
        {
            let source=e.emit("flag_spawn","flag_spawn_failed",json!({"site_id":site_id,"position":p,"occupant":e.state.units[j].id,"carrying":e.state.units[j].carrying,"reason":"occupied_by_carrier","schedule":e.state.sites[i].scheduled_by}));
            schedule(e, i, "retry", source);
        } else {
            spawn(e, i, "flag_spawn");
        }
    }
}
pub(crate) fn score(e: &mut Engine) {
    for i in 0..e.state.units.len() {
        let u = &e.state.units[i];
        let (Some(p), Some(flag_id)) = (u.position, u.carrying) else {
            continue;
        };
        if !e.map.is_home(u.id.team_id, p) {
            continue;
        }
        let unit = u.id;
        let flag_index = e
            .state
            .flags
            .iter()
            .position(|f| f.id == flag_id)
            .expect("carried flag");
        let site_id = e.state.flags[flag_index].site_id;
        e.state.flags.remove(flag_index);
        e.state.units[i].carrying = None;
        let before = e.state.scores[unit.team_id as usize];
        e.state.scores[unit.team_id as usize] += 1;
        let score=e.emit("score","score",json!({"unit":unit,"team_id":unit.team_id,"flag_id":flag_id,"site_id":site_id,"before":before,"after":before+1}));
        e.emit("score","carry_change",json!({"unit":unit,"before":flag_id,"after":null,"reason":"home_return","source":score}));
        let removed=e.emit("score","flag_removed",json!({"flag_id":flag_id,"site_id":site_id,"reason":"home_return","unit":unit,"source":score}));
        let site_index = e
            .state
            .sites
            .iter()
            .position(|s| s.site_id == site_id)
            .expect("source site");
        e.state.sites[site_index].active_flag_id = None;
        e.state.sites[site_index].origin = "after_return".into();
        schedule(e, site_index, "after_return", removed);
    }
}
