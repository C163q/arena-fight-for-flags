use fff_ai_worker::CallReport;
use fff_engine::*;
use fff_replay::*;
use std::path::{Path, PathBuf};
fn record(name: &str, complete: bool) -> PathBuf {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let raw = std::fs::read_to_string(root.join("maps/arena_2p.ron"))
        .unwrap()
        .replace("max_turns: 500", "max_turns: 3");
    let map: MapDefinition = ron::from_str(&raw).unwrap();
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
                elapsed_us: if team == 0 { 50_100 } else { 100 },
                init_elapsed_us: 0,
                restart_count: 0,
                actions: [Action::Wait; 3],
                raw_output: None,
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
