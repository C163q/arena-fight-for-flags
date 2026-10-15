use fff_ai_abi::CtfTeamAction;
use fff_ai_worker::CallReport;
use fff_engine::*;
use fff_replay::*;
use std::path::{Path, PathBuf};
fn record(name: &str, complete: bool) -> PathBuf {
    record_timed(name, complete, [100; 3])
}
fn record_timed(name: &str, complete: bool, elapsed: [u64; 3]) -> PathBuf {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut map = MapDefinition::load(&root.join("maps/arena_2p.ron")).unwrap();
    map.match_limits.max_turns = 3;
    let raw = ron::to_string(&map).unwrap();
    let config = Config::default();
    let mut engine = Engine::new(map.clone(), config.clone(), 42).unwrap();
    let path = std::env::temp_dir().join(format!("fff-replay-{}-{name}", std::process::id()));
    if path.exists() {
        std::fs::remove_dir_all(&path).unwrap();
    }
    let teams = (0..2)
        .map(|team_id| AiInfo {
            team_id,
            name: "bot </script><script>alert(1)</script>".into(),
            library_path: "not-present.so".into(),
            library_sha256: "0".repeat(64),
            ai_seed: None,
        })
        .collect();
    let mut recorder =
        Recorder::create(&path, &map, &config, 42, engine.snapshot(), teams, &raw).unwrap();
    for turn in 1..=3 {
        engine.begin_turn().unwrap();
        let actions = vec![[Action::Wait; 3]; 2];
        let frame = engine.resolve_turn(actions).unwrap();
        let calls = (0..2)
            .map(|team| CallReport {
                team_id: team,
                turn,
                status: if team == 0 { "timeout" } else { "ok" }.into(),
                elapsed_us: if team == 0 {
                    50_100
                } else {
                    elapsed[(turn - 1) as usize]
                },
                init_elapsed_us: 0,
                restart_count: 0,
                actions: [Action::Wait; 3],
                raw_output: if team == 0 {
                    None
                } else {
                    Some(CtfTeamAction::waits())
                },
                error: None,
            })
            .collect::<Vec<_>>();
        recorder.write(&frame, &calls).unwrap();
    }
    if complete {
        recorder
            .finish(&Summary {
                complete: true,
                turns: 3,
                scores: engine.snapshot().scores.clone(),
                outcome: engine.snapshot().outcome.clone(),
                ai_failures: vec![3, 0],
                illegal_actions: vec![0, 0],
            })
            .unwrap();
    }
    path
}
#[test]
fn full_record_replays_without_ai_libraries_and_ascii_matches_json() {
    let path = record("full", true);
    verify_directory(&path).unwrap();
    let text = std::fs::read_to_string(path.join("frames/000001.txt")).unwrap();
    assert!(
        text.contains("PHASE START")
            && text.contains("PHASE END")
            && text.contains("status=timeout")
    );
    assert!(path.join("map.ron").exists() && path.join("summary.json").exists());
    std::fs::remove_dir_all(path).unwrap();
}
#[test]
fn interrupted_prefix_remains_verifiable_but_missing_or_changed_frame_is_rejected() {
    let path = record("partial", false);
    verify_directory(&path).unwrap();
    std::fs::write(path.join("frames/000002.txt"), "wrong").unwrap();
    assert!(verify_directory(&path).is_err());
    std::fs::remove_file(path.join("frames/000001.json")).unwrap();
    assert!(verify_directory(&path).is_err());
    std::fs::remove_dir_all(path).unwrap();
}
#[test]
fn state_tampering_and_directory_escape_are_rejected() {
    let path = record("tamper", true);
    let file = path.join("frames/000001.json");
    let mut value: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&file).unwrap()).unwrap();
    value["frame"]["end"]["scores"][0] = 99.into();
    std::fs::write(&file, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(verify_directory(&path).is_err());
    std::fs::remove_dir_all(path).unwrap();
    let path = record("escape", true);
    std::fs::remove_file(path.join("map.json")).unwrap();
    std::os::unix::fs::symlink("/etc/passwd", path.join("map.json")).unwrap();
    assert!(verify_directory(&path).is_err());
    std::fs::remove_dir_all(path).unwrap();
}

#[test]
fn successful_calls_reject_missing_or_inconsistent_raw_abi_outputs() {
    for kind in ["version", "slots", "actions", "missing"] {
        let path = record(&format!("raw-{kind}"), true);
        verify_directory(&path).unwrap();
        let file = path.join("frames/000001.json");
        let mut value: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&file).unwrap()).unwrap();
        let raw = &mut value["calls"][1]["raw_output"];
        match kind {
            "version" => raw["abi_version"] = 999.into(),
            "slots" => raw["actions"][2]["unit_id"] = 99.into(),
            "actions" => {
                raw["actions"][0]["kind"] = 2.into();
                raw["actions"][0]["target_x"] = 4.into();
                raw["actions"][0]["target_y"] = 4.into();
            }
            "missing" => *raw = serde_json::Value::Null,
            _ => unreachable!(),
        }
        std::fs::write(&file, serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(
            verify_directory(&path).is_err(),
            "accepted tampered raw output: {kind}"
        );
        std::fs::remove_dir_all(path).unwrap();
    }
}

#[test]
fn replay_verifies_first_turn_allowance_and_preserves_legacy_limits() {
    // Prevent both rejecting new legal records and widening the limits of old
    // records. Recorder generates ASCII from the same actual call metadata.
    let legacy =
        "serial; 50000us per request including IPC; queued time excluded; init 1000ms; exit 100ms";
    for (name, elapsed, policy, valid) in [
        ("budget-first", [250_000, 50_000, 50_000], None, true),
        ("budget-first-over", [250_001, 100, 100], None, false),
        ("budget-later-over", [100, 50_001, 100], None, false),
        ("budget-legacy", [50_000; 3], Some(legacy), true),
        (
            "budget-legacy-over",
            [100_000, 100, 100],
            Some(legacy),
            false,
        ),
        ("budget-unknown", [100; 3], Some("unknown"), false),
    ] {
        let path = record_timed(name, true, elapsed);
        if let Some(policy) = policy {
            let file = path.join("manifest.json");
            let mut manifest: serde_json::Value =
                serde_json::from_slice(&std::fs::read(&file).unwrap()).unwrap();
            manifest["time_policy"] = policy.into();
            std::fs::write(file, serde_json::to_vec(&manifest).unwrap()).unwrap();
        }
        let result = verify_directory(&path);
        assert_eq!(result.is_ok(), valid, "{name}: {result:?}");
        std::fs::remove_dir_all(path).unwrap();
    }
}
