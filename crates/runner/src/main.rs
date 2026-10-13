mod cli;
use fff_ai_worker::{TeamHost, initialization};
use fff_engine::*;
fn run() -> Result<(), String> {
    let Some(options) = cli::parse()? else {
        println!("{}", cli::USAGE);
        return Ok(());
    };
    let map = MapDefinition::load(&options.map)?;
    if options.ais.len() != map.players as usize {
        return Err("AI count does not match map players".into());
    }
    let config = Config {
        flag_respawn_min_turns: options.flag_min,
        flag_respawn_max_turns: options.flag_max,
    };
    let mut engine = Engine::new(map.clone(), config.clone(), options.seed)?;
    let worker = std::env::current_exe()
        .map_err(|e| e.to_string())?
        .parent()
        .ok_or("executable has no parent")?
        .join("fff-ai-worker");
    if !worker.is_file() {
        return Err("fff-ai-worker not found beside runner; build the full workspace".into());
    }
    let mut hosts = Vec::new();
    for (i, path) in options.ais.iter().enumerate() {
        let library =
            std::fs::canonicalize(path).map_err(|e| format!("{}: {e}", path.display()))?;
        hosts.push(TeamHost::new(
            &worker,
            &library,
            initialization(
                &map,
                &config,
                i as u32,
                options
                    .seed
                    .wrapping_add((i as u64).wrapping_mul(0x9e3779b97f4a7c15)),
            ),
        ));
    }
    let mut failures = vec![0u32; map.players as usize];
    let mut invalid = vec![0u32; map.players as usize];
    while engine.snapshot().outcome.is_none() {
        let start = engine.begin_turn()?;
        let calls: Vec<_> = hosts.iter_mut().map(|h| h.decide(&start, &map)).collect();
        for (i, call) in calls.iter().enumerate() {
            if call.status != "ok" {
                failures[i] += 1;
            }
        }
        let frame = engine.resolve_turn(calls.iter().map(|c| c.actions).collect())?;
        for event in &frame.events {
            if event
                .data
                .get("validation")
                .and_then(|v| v.as_str())
                .is_some_and(|v| v != "ok")
            {
                let unit = event.data.get("unit").or_else(|| event.data.get("shooter"));
                if let Some(team) = unit.and_then(|u| u.get("team_id")).and_then(|v| v.as_u64()) {
                    invalid[team as usize] += 1;
                }
            }
        }
    }
    let summary = serde_json::json!({"turns":engine.snapshot().turn,"scores":engine.snapshot().scores,"outcome":engine.snapshot().outcome,"ai_failures":failures,"illegal_actions":invalid});
    println!(
        "{}",
        serde_json::to_string(&summary).map_err(|e| e.to_string())?
    );
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}\n{}", cli::USAGE);
        std::process::exit(1);
    }
}
