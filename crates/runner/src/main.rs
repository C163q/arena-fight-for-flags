mod cli;
use fff_ai_worker::{TeamHost, initialization};
use fff_engine::*;
use fff_replay::{AiInfo, Recorder, Summary};
use sha2::{Digest, Sha256};
use std::io::Read;
fn run() -> Result<(), String> {
    if std::env::args_os()
        .nth(1)
        .is_some_and(|s| s == "inspect-map")
    {
        let args = std::env::args_os().collect::<Vec<_>>();
        if args.len() != 3 {
            return Err("usage: fff-runner inspect-map MAP.ron".into());
        }
        let map = MapDefinition::load(std::path::Path::new(&args[2]))?;
        println!(
            "{}",
            serde_json::to_string(&map).map_err(|e| e.to_string())?
        );
        return Ok(());
    }
    if std::env::args_os().nth(1).is_some_and(|s| s == "verify") {
        let args = std::env::args_os().collect::<Vec<_>>();
        if args.len() != 3 {
            return Err("usage: fff-runner verify MATCH_DIR".into());
        }
        fff_replay::verify_directory(std::path::Path::new(&args[2]))?;
        println!("{}", serde_json::json!({"verified":true}));
        return Ok(());
    }
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
    let map = engine.map().clone();
    let worker = std::env::current_exe()
        .map_err(|e| e.to_string())?
        .parent()
        .ok_or("executable has no parent")?
        .join("fff-ai-worker");
    if !worker.is_file() {
        return Err("fff-ai-worker not found beside runner; build the full workspace".into());
    }
    let mut hosts = Vec::new();
    let mut teams = Vec::new();
    for (i, path) in options.ais.iter().enumerate() {
        let ai_seed = match options.ai_seeds.get(i) {
            Some(seed) => *seed,
            None => random_ai_seed()?,
        };
        let library =
            std::fs::canonicalize(path).map_err(|e| format!("{}: {e}", path.display()))?;
        let mut file = std::fs::File::open(&library).map_err(|e| e.to_string())?;
        let mut digest = Sha256::new();
        let mut buffer = [0u8; 16384];
        loop {
            let n = file.read(&mut buffer).map_err(|e| e.to_string())?;
            if n == 0 {
                break;
            }
            digest.update(&buffer[..n]);
        }
        teams.push(AiInfo {
            team_id: i as u32,
            name: library
                .file_stem()
                .map_or_else(|| format!("team{i}"), |s| s.to_string_lossy().into_owned()),
            library_path: library.to_string_lossy().into_owned(),
            library_sha256: format!("{:x}", digest.finalize()),
            ai_seed: Some(ai_seed),
        });
        hosts.push(TeamHost::new(
            &worker,
            &library,
            initialization(&map, &config, i as u32, ai_seed),
        ));
    }
    let raw = std::fs::read_to_string(&options.map).map_err(|e| e.to_string())?;
    let mut recorder = Recorder::create(
        &options.out,
        &map,
        &config,
        options.seed,
        engine.snapshot(),
        teams,
        &raw,
    )?;
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
        recorder.write(&frame, &calls)?;
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
    let summary = Summary {
        complete: true,
        turns: engine.snapshot().turn,
        scores: engine.snapshot().scores.clone(),
        outcome: engine.snapshot().outcome.clone(),
        ai_failures: failures,
        illegal_actions: invalid,
    };
    recorder.finish(&summary)?;
    println!(
        "{}",
        serde_json::to_string(&summary).map_err(|e| e.to_string())?
    );
    Ok(())
}
fn random_ai_seed() -> Result<u64, String> {
    let mut bytes = [0u8; 8];
    std::fs::File::open("/dev/urandom")
        .and_then(|mut file| file.read_exact(&mut bytes))
        .map_err(|e| format!("independent AI seed: {e}"))?;
    Ok(u64::from_le_bytes(bytes))
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}\n{}", cli::USAGE);
        std::process::exit(1);
    }
}
