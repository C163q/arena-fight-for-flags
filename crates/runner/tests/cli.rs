use std::{path::Path, process::Command};
fn map_with_limit(path: &Path, turns: u32) -> String {
    let map = fff_engine::MapDefinition::load(path).unwrap();
    std::fs::read_to_string(path).unwrap().replace(
        &format!("max_turns: {}", map.match_limits.max_turns),
        &format!("max_turns: {turns}"),
    )
}
#[test]
fn match_uses_ron_limits_and_rejects_unknown_overrides_or_wrong_team_count() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let dir = std::env::temp_dir().join(format!("fff-cli-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let source = dir.join("wait.c");
    let library = dir.join("wait.so");
    std::fs::write(&source,r#"
#include "ctf_ai.h"
static uint64_t seen_seed;
uint32_t ctf_abi_version(void){return 1;}
int32_t ctf_create(const CtfInit *i,void **c){seen_seed=i->seed;*c=0;return 0;}
int32_t ctf_decide(void *c,const CtfObservation *o,CtfTeamAction *a){(void)c;(void)o;a->abi_version=1;a->struct_size=sizeof(*a);for(uint32_t i=0;i<3;i++){a->actions[i]=(CtfAction){.unit_id=i,.target_x=(int32_t)(seen_seed&0x7fffffffu)};}return 0;}
void ctf_destroy(void *c){(void)c;}
"#).unwrap();
    assert!(
        Command::new("cc")
            .args(["-shared", "-fPIC"])
            .arg("-I")
            .arg(root.join("include"))
            .arg(source)
            .arg("-o")
            .arg(&library)
            .status()
            .unwrap()
            .success()
    );
    let map = map_with_limit(&root.join("maps/arena_2p.ron"), 2);
    let path = dir.join("map.ron");
    std::fs::write(&path, map).unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_fff-runner"))
        .arg("--map")
        .arg(&path)
        .arg("--ai")
        .arg(&library)
        .arg("--ai")
        .arg(&library)
        .arg("--out")
        .arg(dir.join("match"))
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let summary: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(summary["turns"], 2);
    assert_eq!(summary["scores"], serde_json::json!([0, 0]));
    assert_eq!(summary["ai_failures"], serde_json::json!([0, 0]));
    assert!(dir.join("match/frames/000002.json").is_file());
    assert!(dir.join("match/frames/000002.txt").is_file());
    let verified = Command::new(env!("CARGO_BIN_EXE_fff-runner"))
        .arg("verify")
        .arg(dir.join("match"))
        .output()
        .unwrap();
    assert!(
        verified.status.success(),
        "{}",
        String::from_utf8_lossy(&verified.stderr)
    );
    assert!(
        !Command::new(env!("CARGO_BIN_EXE_fff-runner"))
            .args(["--turns", "1"])
            .status()
            .unwrap()
            .success()
    );
    assert!(
        !Command::new(env!("CARGO_BIN_EXE_fff-runner"))
            .arg("--map")
            .arg(&path)
            .arg("--ai")
            .arg(&library)
            .arg("--out")
            .arg(dir.join("wrong"))
            .status()
            .unwrap()
            .success()
    );
    let map8 = map_with_limit(&root.join("maps/arena_8p.ron"), 2);
    let path8 = dir.join("eight.ron");
    std::fs::write(&path8, map8).unwrap();
    let mut command = Command::new(env!("CARGO_BIN_EXE_fff-runner"));
    command
        .arg("--map")
        .arg(&path8)
        .arg("--out")
        .arg(dir.join("eight"));
    for _ in 0..8 {
        command.arg("--ai").arg(&library);
    }
    let result = command.output().unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    let summary: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(
        summary["scores"],
        serde_json::json!([0, 0, 0, 0, 0, 0, 0, 0])
    );
    assert_eq!(
        summary["ai_failures"],
        serde_json::json!([0, 0, 0, 0, 0, 0, 0, 0])
    );
    let manifest_a: serde_json::Value =
        serde_json::from_slice(&std::fs::read(dir.join("match/manifest.json")).unwrap()).unwrap();
    let repeated = Command::new(env!("CARGO_BIN_EXE_fff-runner"))
        .arg("--map")
        .arg(&path)
        .arg("--ai")
        .arg(&library)
        .arg("--ai")
        .arg(&library)
        .arg("--out")
        .arg(dir.join("repeat"))
        .output()
        .unwrap();
    assert!(repeated.status.success());
    let manifest_b: serde_json::Value =
        serde_json::from_slice(&std::fs::read(dir.join("repeat/manifest.json")).unwrap()).unwrap();
    let seeds_a = manifest_a["teams"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["ai_seed"].as_u64().expect("AI seed must be recorded"))
        .collect::<Vec<_>>();
    let seeds_b = manifest_b["teams"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["ai_seed"].as_u64().expect("AI seed must be recorded"))
        .collect::<Vec<_>>();
    assert_ne!(
        seeds_a, seeds_b,
        "default AI seed must be independent of the repeated engine seed"
    );
    assert_eq!(
        std::fs::read(dir.join("match/initial.json")).unwrap(),
        std::fs::read(dir.join("repeat/initial.json")).unwrap()
    );
    let explicit = Command::new(env!("CARGO_BIN_EXE_fff-runner"))
        .arg("--map")
        .arg(&path)
        .arg("--ai")
        .arg(&library)
        .arg("--ai")
        .arg(&library)
        .args(["--ai-seed", "314", "--ai-seed", "159"])
        .arg("--out")
        .arg(dir.join("seeded"))
        .output()
        .unwrap();
    assert!(
        explicit.status.success(),
        "{}",
        String::from_utf8_lossy(&explicit.stderr)
    );
    let manifest: serde_json::Value =
        serde_json::from_slice(&std::fs::read(dir.join("seeded/manifest.json")).unwrap()).unwrap();
    assert_eq!(manifest["teams"][0]["ai_seed"], 314);
    assert_eq!(manifest["teams"][1]["ai_seed"], 159);
    let frame: serde_json::Value =
        serde_json::from_slice(&std::fs::read(dir.join("seeded/frames/000001.json")).unwrap())
            .unwrap();
    assert_eq!(
        frame["calls"][0]["raw_output"]["actions"][0]["target_x"],
        314
    );
    assert_eq!(
        frame["calls"][1]["raw_output"]["actions"][0]["target_x"],
        159
    );
    // SAFETY: test process adopts and reaps the runner's orphan workers.
    assert_eq!(
        unsafe { libc::prctl(libc::PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) },
        0
    );
    // A user interrupt or forced parent exit must not strand paused workers.
    let long_ron = map_with_limit(&root.join("maps/arena_2p.ron"), 1000000);
    let long_map = dir.join("long.ron");
    std::fs::write(&long_map, long_ron).unwrap();
    let mut parent = Command::new(env!("CARGO_BIN_EXE_fff-runner"))
        .arg("--map")
        .arg(long_map)
        .arg("--ai")
        .arg(&library)
        .arg("--ai")
        .arg(&library)
        .arg("--out")
        .arg(dir.join("interrupted"))
        .stdout(std::process::Stdio::null())
        .spawn()
        .unwrap();
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(2);
    let children = loop {
        let content = std::fs::read_to_string(format!(
            "/proc/{}/task/{}/children",
            parent.id(),
            parent.id()
        ))
        .unwrap_or_default();
        let pids = content
            .split_whitespace()
            .map(|s| s.parse::<u32>().unwrap())
            .collect::<Vec<_>>();
        if pids.len() == 2 {
            break pids;
        }
        assert!(
            std::time::Instant::now() < deadline,
            "workers did not start"
        );
        std::thread::sleep(std::time::Duration::from_millis(5));
    };
    parent.kill().unwrap();
    parent.wait().unwrap();
    // Seeing two /proc children does not imply both workers have finished
    // startup. Give their parent check/signal handler a bounded scheduling
    // window, rather than assuming every loaded machine schedules it in 50ms.
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(1);
    let mut stranded = children;
    while !stranded.is_empty() && std::time::Instant::now() < deadline {
        stranded.retain(|&pid| {
            let mut status = 0;
            // SAFETY: these known children were adopted after their parent exited.
            let result = unsafe { libc::waitpid(pid as i32, &mut status, libc::WNOHANG) };
            if result < 0 {
                assert_eq!(
                    std::io::Error::last_os_error().raw_os_error(),
                    Some(libc::ECHILD)
                );
            }
            result == 0
        });
        if !stranded.is_empty() {
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
    }
    for pid in &stranded {
        // SAFETY: each PID is a live child owned by this test.
        unsafe {
            libc::kill(*pid as i32, libc::SIGKILL);
            libc::waitpid(*pid as i32, std::ptr::null_mut(), 0);
        }
    }
    assert!(
        stranded.is_empty(),
        "workers survived parent death: {stranded:?}"
    );
    std::fs::remove_dir_all(dir).unwrap();
}
