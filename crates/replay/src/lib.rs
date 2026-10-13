use fff_ai_worker::CallReport;
use fff_engine::*;
use serde::{Deserialize, Serialize};
use std::path::Path;
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AiInfo {
    pub team_id: u32,
    pub name: String,
    pub library_path: String,
    pub library_sha256: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Manifest {
    pub format_version: u32,
    pub match_id: String,
    pub engine_version: String,
    pub rules_version: String,
    pub rng_version: String,
    pub seed: u64,
    pub config: Config,
    pub map_id: String,
    pub teams: Vec<AiInfo>,
    pub status: String,
    pub last_complete_turn: u32,
    pub time_policy: String,
    pub platform: String,
    pub build_profile: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct InitialRecord {
    pub format_version: u32,
    pub state: Snapshot,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TurnRecord {
    pub format_version: u32,
    pub frame: Frame,
    pub calls: Vec<CallReport>,
    pub call_order: Vec<u32>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Summary {
    pub complete: bool,
    pub turns: u32,
    pub scores: Vec<u32>,
    pub outcome: Option<Outcome>,
    pub ai_failures: Vec<u32>,
    pub illegal_actions: Vec<u32>,
}
mod ascii;
mod verify;
pub use verify::verify_directory;
pub struct Recorder {
    path: std::path::PathBuf,
    map: MapDefinition,
    manifest: Manifest,
    last: Snapshot,
}
impl Recorder {
    pub fn create(
        path: &Path,
        map: &MapDefinition,
        config: &Config,
        seed: u64,
        initial: &Snapshot,
        teams: Vec<AiInfo>,
        raw: &str,
    ) -> Result<Self, String> {
        map.validate()?;
        if teams.len() != map.players as usize
            || teams.iter().enumerate().any(|(i, t)| t.team_id != i as u32)
        {
            return Err("invalid replay team metadata".into());
        }
        let mut source: MapDefinition = ron::from_str(raw).map_err(|e| e.to_string())?;
        source.validate()?;
        source.spawn_regions.sort_by_key(|s| s.team_id);
        source.flag_points.sort_by_key(|s| s.id);
        if &source != map {
            return Err("raw RON differs from normalized map".into());
        }
        if initial.turn != 0
            || Engine::new(map.clone(), config.clone(), seed)?.snapshot() != initial
        {
            return Err("initial state does not match seed and map".into());
        }
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        std::fs::create_dir(path).map_err(|e| format!("{}: {e}", path.display()))?;
        std::fs::create_dir(path.join("frames")).map_err(|e| e.to_string())?;
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|e| e.to_string())?
            .as_micros();
        let manifest=Manifest{format_version:1,match_id:format!("match-{seed}-{stamp}"),engine_version:env!("CARGO_PKG_VERSION").into(),rules_version:RULES_VERSION.into(),rng_version:fff_engine::rng::RNG_VERSION.into(),seed,config:config.clone(),map_id:map.id.clone(),teams,status:"in_progress".into(),last_complete_turn:0,time_policy:"serial; 50000us per request including IPC; queued time excluded; init 1000ms; exit 100ms".into(),platform:format!("{}-{}",std::env::consts::OS,std::env::consts::ARCH),build_profile:if cfg!(debug_assertions){"debug"}else{"release"}.into()};
        let recorder = Self {
            path: path.into(),
            map: map.clone(),
            manifest,
            last: initial.clone(),
        };
        atomic(&recorder.path.join("map.ron"), raw.as_bytes())?;
        json(&recorder.path.join("map.json"), map)?;
        json(
            &recorder.path.join("initial.json"),
            &InitialRecord {
                format_version: 1,
                state: initial.clone(),
            },
        )?;
        atomic(
            &recorder.path.join("initial.txt"),
            ascii::snapshot(map, initial, "INITIAL").as_bytes(),
        )?;
        json(&recorder.path.join("manifest.json"), &recorder.manifest)?;
        Ok(recorder)
    }
    pub fn write(&mut self, frame: &Frame, calls: &[CallReport]) -> Result<(), String> {
        if frame.turn != self.manifest.last_complete_turn + 1
            || calls.len() != self.map.players as usize
        {
            return Err("non-contiguous replay write".into());
        }
        let record = TurnRecord {
            format_version: 1,
            frame: frame.clone(),
            calls: calls.to_vec(),
            call_order: calls.iter().map(|c| c.team_id).collect(),
        };
        let prefix = self.path.join("frames").join(format!("{:06}", frame.turn));
        json(&prefix.with_extension("json"), &record)?;
        atomic(
            &prefix.with_extension("txt"),
            ascii::frame(&self.map, &record).as_bytes(),
        )?;
        self.manifest.last_complete_turn = frame.turn;
        self.last = frame.end.clone();
        json(&self.path.join("manifest.json"), &self.manifest)
    }
    pub fn finish(&mut self, summary: &Summary) -> Result<(), String> {
        if !summary.complete
            || summary.turns != self.manifest.last_complete_turn
            || summary.scores != self.last.scores
            || summary.outcome != self.last.outcome
            || summary.outcome.is_none()
        {
            return Err("summary does not match final state".into());
        }
        json(&self.path.join("summary.json"), summary)?;
        self.manifest.status = "complete".into();
        json(&self.path.join("manifest.json"), &self.manifest)
    }
}
fn atomic(path: &Path, bytes: &[u8]) -> Result<(), String> {
    use std::io::Write;
    let temporary = path.with_extension(format!(
        "{}.tmp",
        path.extension().and_then(|s| s.to_str()).unwrap_or("data")
    ));
    let mut file =
        std::fs::File::create(&temporary).map_err(|e| format!("{}: {e}", temporary.display()))?;
    file.write_all(bytes)
        .and_then(|()| file.sync_all())
        .map_err(|e| e.to_string())?;
    std::fs::rename(&temporary, path).map_err(|e| format!("{}: {e}", path.display()))
}
fn json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let mut bytes = serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?;
    bytes.push(b'\n');
    atomic(path, &bytes)
}
