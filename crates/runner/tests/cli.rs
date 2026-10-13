use std::{path::Path, process::Command};
#[test]
fn match_uses_ron_limits_and_rejects_unknown_overrides_or_wrong_team_count() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let dir = std::env::temp_dir().join(format!("fff-cli-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let source = dir.join("wait.c");
    let library = dir.join("wait.so");
    std::fs::write(&source,r#"
#include "ctf_ai.h"
uint32_t ctf_abi_version(void){return 1;}
int32_t ctf_create(const CtfInit *i,void **c){(void)i;*c=0;return 0;}
int32_t ctf_decide(void *c,const CtfObservation *o,CtfTeamAction *a){(void)c;(void)o;a->abi_version=1;a->struct_size=sizeof(*a);for(uint32_t i=0;i<3;i++){a->actions[i]=(CtfAction){.unit_id=i};}return 0;}
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
    let map = std::fs::read_to_string(root.join("maps/arena_2p.ron"))
        .unwrap()
        .replace("max_turns: 500", "max_turns: 2");
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
    let map8 = std::fs::read_to_string(root.join("maps/arena_8p.ron"))
        .unwrap()
        .replace("max_turns: 1200", "max_turns: 2");
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
    // SAFETY: test process adopts and reaps the runner's orphan workers.
    assert_eq!(
        unsafe { libc::prctl(libc::PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) },
        0
    );
    // A user interrupt or forced parent exit must not strand paused workers.
    let long_ron = std::fs::read_to_string(root.join("maps/arena_2p.ron"))
        .unwrap()
        .replace("max_turns: 500", "max_turns: 1000000");
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
    std::thread::sleep(std::time::Duration::from_millis(50));
    let mut stranded = Vec::new();
    for &pid in &children {
        let mut status = 0;
        // SAFETY: these known children were adopted after their parent exited.
        let result = unsafe { libc::waitpid(pid as i32, &mut status, libc::WNOHANG) };
        if result == 0 {
            stranded.push(pid);
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
