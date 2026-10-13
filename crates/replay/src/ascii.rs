use crate::*;
use std::fmt::Write;
fn symbol(id: UnitId) -> char {
    char::from(b'A' + (id.team_id * 3 + id.unit_id) as u8)
}
pub fn snapshot(map: &MapDefinition, state: &Snapshot, phase: &str) -> String {
    let mut text = format!(
        "TURN {} PHASE {phase}\nCOORD x=right y=down ORIGIN top-left\nSCORE",
        state.turn
    );
    for (i, score) in state.scores.iter().enumerate() {
        let _ = write!(text, " team{i}={score}");
    }
    text.push_str("\nLEGEND #=wall .=floor 0-7=home o=flag-site *=ground-flag A-X=units\n");
    let mut board = map
        .terrain
        .iter()
        .map(|s| s.as_bytes().to_vec())
        .collect::<Vec<_>>();
    for home in &map.spawn_regions {
        for y in home.y..home.y + 3 {
            for x in home.x..home.x + 3 {
                board[y as usize][x as usize] = b'0' + home.team_id as u8;
            }
        }
    }
    for point in &map.flag_points {
        board[point.y as usize][point.x as usize] = b'o';
    }
    for flag in &state.flags {
        if let FlagLocation::Ground { position } = flag.location {
            board[position.y as usize][position.x as usize] = b'*';
        }
    }
    for unit in &state.units {
        if let Some(p) = unit.position {
            board[p.y as usize][p.x as usize] = symbol(unit.id) as u8;
        }
    }
    for divisor in [100, 10, 1] {
        if divisor == 1 || map.width > divisor {
            text.push_str("     ");
            for x in 0..map.width {
                let _ = write!(text, "{}", (x / divisor) % 10);
            }
            text.push('\n');
        }
    }
    for (y, row) in board.into_iter().enumerate() {
        let _ = writeln!(
            text,
            "{y:>4} {}",
            String::from_utf8(row).expect("ASCII board")
        );
    }
    text.push_str("UNITS\n");
    for unit in &state.units {
        let position = unit
            .position
            .map_or_else(|| "none".into(), |p| format!("({},{})", p.x, p.y));
        let carry = unit
            .carrying
            .map_or_else(|| "none".into(), |id| format!("flag{id}"));
        let _ = writeln!(
            text,
            "team{} unit{} {} {} pos={} hp={} carry={} respawn_at_turn={}",
            unit.id.team_id,
            unit.id.unit_id,
            symbol(unit.id),
            if unit.position.is_some() {
                "alive"
            } else {
                "dead"
            },
            position,
            unit.hp,
            carry,
            unit.respawn_at_turn
                .map_or_else(|| "none".into(), |t| t.to_string())
        );
    }
    text.push_str("FLAG_SITES\n");
    for p in &map.flag_points {
        let _ = writeln!(text, "site{} pos=({},{})", p.id, p.x, p.y);
    }
    text.push_str("FLAGS\n");
    if state.flags.is_empty() {
        text.push_str("none\n");
    }
    for flag in &state.flags {
        let location = match flag.location {
            FlagLocation::Ground { position } => format!("ground=({},{})", position.x, position.y),
            FlagLocation::Carried { unit } => {
                format!("carried_by=team{}.unit{}", unit.team_id, unit.unit_id)
            }
        };
        let _ = writeln!(
            text,
            "flag{} source=site{} {}",
            flag.id, flag.site_id, location
        );
    }
    text
}
pub fn frame(map: &MapDefinition, record: &TurnRecord) -> String {
    let mut text = snapshot(map, &record.frame.end, "END");
    text.push_str("\nAI_CALLS\n");
    for call in &record.calls {
        let _ = writeln!(
            text,
            "team{} status={} elapsed_us={} init_elapsed_us={} restart_count={} error={}",
            call.team_id,
            call.status,
            call.elapsed_us,
            call.init_elapsed_us,
            call.restart_count,
            serde_json::to_string(&call.error).expect("serializable error")
        );
    }
    text.push_str("ACTIONS\n");
    for (team, actions) in record.frame.requested.iter().enumerate() {
        for (unit, action) in actions.iter().enumerate() {
            let _ = writeln!(
                text,
                "team{team}.unit{unit} requested={} applied={}",
                serde_json::to_string(action).expect("action"),
                serde_json::to_string(&record.frame.applied[team][unit]).expect("action")
            );
        }
    }
    text.push_str("EVENTS\n");
    if record.frame.events.is_empty() {
        text.push_str("none\n");
    }
    for event in &record.frame.events {
        let _ = writeln!(
            text,
            "{} phase={} type={} {}",
            event.event_id,
            event.phase,
            event.kind,
            serde_json::to_string(&event.data).expect("event")
        );
    }
    text.push_str("\n");
    text.push_str(&snapshot(map, &record.frame.start, "START"));
    text
}
