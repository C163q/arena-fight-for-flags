use crate::*;
use serde::de::DeserializeOwned;
use std::{
    fs::File,
    io::Read,
    path::{Path, PathBuf},
};
fn read(root: &Path, relative: &str) -> Result<Vec<u8>, String> {
    let path = root.join(relative);
    let actual = std::fs::canonicalize(&path).map_err(|e| format!("{}: {e}", path.display()))?;
    if !actual.starts_with(root) {
        return Err(format!("path escapes replay directory: {relative}"));
    }
    let mut bytes = Vec::new();
    File::open(&actual)
        .map_err(|e| e.to_string())?
        .take(16_777_217)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() > 16_777_216 {
        return Err(format!("file too large: {relative}"));
    }
    Ok(bytes)
}
fn decode<T: DeserializeOwned>(root: &Path, relative: &str) -> Result<T, String> {
    serde_json::from_slice(&read(root, relative)?).map_err(|e| format!("{relative}: {e}"))
}
pub fn verify_directory(path: &Path) -> Result<(), String> {
    let root: PathBuf = std::fs::canonicalize(path).map_err(|e| e.to_string())?;
    let manifest: Manifest = decode(&root, "manifest.json")?;
    if manifest.format_version != 1
        || manifest.rules_version != RULES_VERSION
        || manifest.rng_version != fff_engine::rng::RNG_VERSION
    {
        return Err("unsupported replay/rules/RNG version".into());
    }
    if !["in_progress", "complete"].contains(&manifest.status.as_str()) {
        return Err("invalid recording status".into());
    }
    let map: MapDefinition = decode(&root, "map.json")?;
    map.validate()?;
    let mut ron: MapDefinition =
        ron::from_str(std::str::from_utf8(&read(&root, "map.ron")?).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    ron.spawn_regions.sort_by_key(|s| s.team_id);
    ron.flag_points.sort_by_key(|s| s.id);
    if ron != map
        || manifest.map_id != map.id
        || manifest.last_complete_turn > map.match_limits.max_turns
        || manifest.teams.len() != map.players as usize
        || manifest
            .teams
            .iter()
            .enumerate()
            .any(|(i, t)| t.team_id != i as u32)
    {
        return Err("manifest/map metadata mismatch".into());
    }
    let initial: InitialRecord = decode(&root, "initial.json")?;
    let mut engine = Engine::new(map.clone(), manifest.config.clone(), manifest.seed)?;
    if initial.format_version != 1 || &initial.state != engine.snapshot() {
        return Err("initial state does not match seed".into());
    }
    if read(&root, "initial.txt")? != ascii::snapshot(&map, &initial.state, "INITIAL").as_bytes() {
        return Err("initial.txt differs from JSON".into());
    }
    let mut failures = vec![0; map.players as usize];
    let mut invalid = vec![0; map.players as usize];
    for turn in 1..=manifest.last_complete_turn {
        let file = format!("frames/{turn:06}.json");
        let record: TurnRecord = decode(&root, &file)?;
        if record.format_version != 1
            || record.frame.turn != turn
            || record.calls.len() != map.players as usize
            || record.call_order != (0..map.players).collect::<Vec<_>>()
        {
            return Err(format!("{file}: invalid frame/call metadata"));
        }
        let start = engine.begin_turn()?;
        if record.frame.start != start {
            return Err(format!("{file}: START state differs"));
        }
        for (i, call) in record.calls.iter().enumerate() {
            if call.team_id != i as u32
                || call.turn != turn
                || record.frame.requested.get(i) != Some(&call.actions)
                || ![
                    "ok",
                    "timeout",
                    "crash",
                    "load_error",
                    "protocol_error",
                    "ai_error",
                ]
                .contains(&call.status.as_str())
            {
                return Err(format!("{file}: call/action mismatch"));
            }
            if call.status != "ok" {
                failures[i] += 1;
                if call.actions != [Action::Wait; 3] {
                    return Err(format!("{file}: failed AI must wait"));
                }
            } else {
                if call.elapsed_us > 50_000 {
                    return Err(format!("{file}: accepted response exceeded 50ms"));
                }
                let raw = call
                    .raw_output
                    .as_ref()
                    .ok_or_else(|| format!("{file}: successful call missing raw ABI output"))?;
                let decoded =
                    fff_ai_worker::decode_output(raw).map_err(|e| format!("{file}: {e}"))?;
                if decoded != call.actions {
                    return Err(format!(
                        "{file}: raw ABI output differs from submitted actions"
                    ));
                }
            }
        }
        let actual = engine.resolve_turn(record.frame.requested.clone())?;
        if actual != record.frame {
            return Err(format!("{file}: rules, events or END state differ"));
        }
        for event in &actual.events {
            if event
                .data
                .get("validation")
                .and_then(|v| v.as_str())
                .is_some_and(|v| v != "ok")
                && let Some(team) = event
                    .data
                    .get("unit")
                    .or_else(|| event.data.get("shooter"))
                    .and_then(|u| u.get("team_id"))
                    .and_then(|v| v.as_u64())
            {
                invalid[team as usize] += 1;
            }
        }
        if read(&root, &format!("frames/{turn:06}.txt"))? != ascii::frame(&map, &record).as_bytes()
        {
            return Err(format!("frames/{turn:06}.txt differs from JSON"));
        }
    }
    if manifest.status == "complete" {
        let summary: Summary = decode(&root, "summary.json")?;
        if !summary.complete
            || summary.turns != manifest.last_complete_turn
            || summary.scores != engine.snapshot().scores
            || summary.outcome != engine.snapshot().outcome
            || summary.outcome.is_none()
            || summary.ai_failures != failures
            || summary.illegal_actions != invalid
        {
            return Err("summary differs from recorded match".into());
        }
    }
    Ok(())
}
