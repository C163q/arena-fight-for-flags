use std::path::PathBuf;
pub const USAGE: &str = "fff-runner --map MAP.ron --ai TEAM.so --ai TEAM.so [--ai ...] --out MATCH_DIR [--seed N] [--flag-min-turns 5 --flag-max-turns 15]";
pub struct Options {
    pub map: PathBuf,
    pub ais: Vec<PathBuf>,
    pub out: PathBuf,
    pub seed: u64,
    pub flag_min: u32,
    pub flag_max: u32,
}
pub fn parse() -> Result<Option<Options>, String> {
    let mut args = std::env::args_os().skip(1);
    let mut map = None;
    let mut out = None;
    let mut ais = Vec::new();
    let mut seed = 0;
    let mut flag_min = 5;
    let mut flag_max = 15;
    while let Some(arg) = args.next() {
        if arg == "--help" || arg == "-h" {
            return Ok(None);
        }
        let key = arg.to_str().ok_or("argument is not UTF-8")?;
        if ![
            "--map",
            "--ai",
            "--out",
            "--seed",
            "--flag-min-turns",
            "--flag-max-turns",
        ]
        .contains(&key)
        {
            return Err(format!("unknown argument: {key}"));
        }
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {key}"))?;
        match key {
            "--map" => {
                if map.replace(PathBuf::from(value)).is_some() {
                    return Err("duplicate --map".into());
                }
            }
            "--out" => {
                if out.replace(PathBuf::from(value)).is_some() {
                    return Err("duplicate --out".into());
                }
            }
            "--ai" => ais.push(PathBuf::from(value)),
            "--seed" => {
                seed = value
                    .to_str()
                    .ok_or("invalid seed")?
                    .parse()
                    .map_err(|_| "invalid seed")?
            }
            "--flag-min-turns" => {
                flag_min = value
                    .to_str()
                    .ok_or("invalid flag min")?
                    .parse()
                    .map_err(|_| "invalid flag min")?
            }
            "--flag-max-turns" => {
                flag_max = value
                    .to_str()
                    .ok_or("invalid flag max")?
                    .parse()
                    .map_err(|_| "invalid flag max")?
            }
            _ => unreachable!(),
        }
    }
    let options = Options {
        map: map.ok_or("--map is required")?,
        ais,
        out: out.ok_or("--out is required")?,
        seed,
        flag_min,
        flag_max,
    };
    if !(2..=8).contains(&options.ais.len()) {
        return Err("--ai must be supplied for 2–8 teams".into());
    }
    if options.out.exists() {
        return Err(format!("output already exists: {}", options.out.display()));
    }
    Ok(Some(options))
}
