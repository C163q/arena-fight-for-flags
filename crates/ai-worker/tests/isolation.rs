use fff_ai_worker::*;
use fff_engine::*;
use std::{
    path::{Path, PathBuf},
    time::{Duration, Instant},
};
fn compile(root: &Path, dir: &Path, name: &str, version: u32) -> PathBuf {
    let c = dir.join(format!("{name}.c"));
    let so = dir.join(format!("{name}.so"));
    std::fs::write(&c,r#"
#include "ctf_ai.h"
#include <stdlib.h>
#include <pthread.h>
#include <unistd.h>
#ifndef VERSION
#define VERSION 1
#endif
static void *busy(void *p){(void)p;for(;;){}return NULL;}
uint32_t ctf_abi_version(void){return VERSION;}
int32_t ctf_create(const CtfInit *init,void **out){
 if(init->seed==4){for(;;){}}
 uint32_t *p=malloc(2*sizeof(uint32_t));p[0]=(uint32_t)init->seed;p[1]=init->restart_count;*out=p;return 0;
}
int32_t ctf_decide(void *ctx,const CtfObservation *obs,CtfTeamAction *out){
 uint32_t *p=ctx;(void)obs;
 if(p[0]==1||(p[0]==5&&p[1]==0)){for(;;){}}
 if(p[0]==2){abort();}
 if(p[0]==9||p[0]==10){
  if(obs->turn==1){usleep(p[0]==9?100000:350000);}
  if(obs->turn==2){usleep(100000);}
 }
 if(p[0]==7){pthread_t t;pthread_create(&t,NULL,busy,NULL);}
 out->abi_version=1;out->struct_size=sizeof(*out);
 for(uint32_t i=0;i<3;i++){out->actions[i]=(CtfAction){.unit_id=i,.kind=CTF_WAIT};}
 if(p[0]==9||p[0]==10){
  out->actions[0]=(CtfAction){.unit_id=0,.kind=CTF_MOVE,.direction=CTF_RIGHT};
 }
 if(p[0]==3){out->actions[2].unit_id=99;}
 if(p[0]==8){out->actions[0].kind=999;}
 return 0;
}
void ctf_destroy(void *ctx){uint32_t *p=ctx;if(p[0]==6){for(;;){}}free(p);}
"#).unwrap();
    assert!(
        std::process::Command::new("cc")
            .args(["-shared", "-fPIC", "-O0", "-pthread"])
            .arg(format!("-DVERSION={version}"))
            .arg("-I")
            .arg(root.join("include"))
            .arg(c)
            .arg("-o")
            .arg(&so)
            .status()
            .unwrap()
            .success()
    );
    so
}
#[test]
fn actual_c_libraries_are_isolated_timed_restarted_and_paused() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let dir = std::env::temp_dir().join(format!("fff-worker-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let library = compile(&root, &dir, "fixture", 1);
    let wrong = compile(&root, &dir, "wrong", 999);
    let map = MapDefinition::load(&root.join("maps/arena_2p.ron")).unwrap();
    let config = Config::default();
    let mut engine = Engine::new(map.clone(), config.clone(), 4).unwrap();
    let state = engine.begin_turn().unwrap();
    let worker = Path::new(env!("CARGO_BIN_EXE_fff-ai-worker"));
    for (seed, want) in [
        (0, "ok"),
        (1, "timeout"),
        (2, "crash"),
        (3, "protocol_error"),
        (4, "load_error"),
    ] {
        let mut host = TeamHost::new(worker, &library, initialization(&map, &config, 0, seed));
        let start = Instant::now();
        let report = host.decide(&state, &map);
        assert_eq!(report.status, want, "seed {seed}: {:?}", report.error);
        assert!(start.elapsed() < Duration::from_secs(3));
        if want != "ok" {
            assert_eq!(report.actions, [Action::Wait; 3]);
            assert!(host.pid().is_none());
        }
    }
    let mut host = TeamHost::new(worker, &wrong, initialization(&map, &config, 0, 0));
    assert_eq!(host.decide(&state, &map).status, "load_error");
    let mut host = TeamHost::new(worker, &library, initialization(&map, &config, 0, 5));
    assert_eq!(host.decide(&state, &map).status, "timeout");
    assert_eq!(host.decide(&state, &map).status, "ok");
    let mut host = TeamHost::new(worker, &library, initialization(&map, &config, 0, 7));
    assert_eq!(host.decide(&state, &map).status, "ok");
    let pid = host.pid().unwrap();
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
    assert!(stat.contains(") T "));
    drop(host);
    assert!(!Path::new(&format!("/proc/{pid}")).exists());
    let mut host = TeamHost::new(worker, &library, initialization(&map, &config, 0, 6));
    assert_eq!(host.decide(&state, &map).status, "ok");
    let at = Instant::now();
    drop(host);
    assert!(at.elapsed() < Duration::from_secs(1));
    let mut host = TeamHost::new(worker, &library, initialization(&map, &config, 0, 8));
    let report = host.decide(&state, &map);
    assert_eq!(report.status, "ok");
    assert!(matches!(
        report.actions[0],
        Action::Invalid { kind_code: 999, .. }
    ));
    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn first_match_turn_has_extra_time_but_restarts_do_not() {
    // A 50ms first-turn deadline loses the first move; a per-process grace
    // period incorrectly accepts the 100ms call after a timeout and restart.
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let dir = std::env::temp_dir().join(format!("fff-budget-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let library = compile(&root, &dir, "budget", 1);
    let map = MapDefinition::load(&root.join("maps/arena_2p.ron")).unwrap();
    let config = Config::default();
    let mut engine = Engine::new(map.clone(), config.clone(), 4).unwrap();
    let mut state = engine.begin_turn().unwrap();
    let worker = Path::new(env!("CARGO_BIN_EXE_fff-ai-worker"));
    let mut host = TeamHost::new(worker, &library, initialization(&map, &config, 0, 9));
    let report = host.decide(&state, &map);
    assert_eq!(report.status, "ok", "{:?}", report.error);
    assert_eq!(
        report.actions[0],
        Action::Move {
            direction: Direction::Right
        }
    );
    assert!(report.elapsed_us >= 100_000);
    state.turn = 2;
    let report = host.decide(&state, &map);
    assert_eq!(report.status, "timeout");
    assert_eq!(report.actions, [Action::Wait; 3]);
    assert!(host.pid().is_none());
    state.turn = 3;
    let report = host.decide(&state, &map);
    assert_eq!(report.status, "ok");
    assert_eq!(report.restart_count, 1);
    drop(host);

    let mut host = TeamHost::new(worker, &library, initialization(&map, &config, 0, 10));
    state.turn = 1;
    let report = host.decide(&state, &map);
    assert_eq!(report.status, "timeout");
    assert!(report.elapsed_us >= 250_000);
    assert_eq!(report.actions, [Action::Wait; 3]);
    state.turn = 2;
    let report = host.decide(&state, &map);
    assert_eq!(report.status, "timeout", "restart must not get 250ms");
    assert_eq!(report.restart_count, 1);
    assert_eq!(report.actions, [Action::Wait; 3]);
    state.turn = 3;
    assert_eq!(host.decide(&state, &map).status, "ok");
    drop(host);
    std::fs::remove_dir_all(dir).unwrap();
}
