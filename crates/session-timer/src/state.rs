use crate::{Error, clock};
use std::{
    fs::{File, OpenOptions, Permissions},
    io::{Read, Seek, SeekFrom, Write},
    os::{
        fd::AsRawFd,
        unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    },
    path::Path,
};

const MAGIC: &str = "FFF_TIMER_V1";
const MAX_RECORD: u64 = 128;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Record {
    pub pid: i32,
    pub start_ns: u64,
}

// POSIX locks belong to a process: closing *any* descriptor for this inode
// releases that process's locks. The timer retains exactly this one descriptor
// and never calls query_record in its own process. The query is a separate bin.
pub(crate) struct Session {
    file: File,
    pub(crate) record: Record,
}

fn check_file(file: &File) -> Result<(), Error> {
    let meta = file.metadata()?;
    if !meta.is_file() || meta.nlink() != 1 {
        return Err(Error::InvalidState);
    }
    Ok(())
}
fn request(kind: libc::c_short, start: libc::off_t, len: libc::off_t) -> libc::flock {
    libc::flock {
        l_type: kind,
        l_whence: libc::SEEK_SET as libc::c_short,
        l_start: start,
        l_len: len,
        l_pid: 0,
    }
}
fn set_lock(file: &File, kind: libc::c_short, start: i64, len: i64) -> Result<(), Error> {
    let value = request(kind, start, len);
    // SAFETY: file owns a valid descriptor and value has the platform C layout;
    // fcntl reads it synchronously and retains no pointer.
    if unsafe { libc::fcntl(file.as_raw_fd(), libc::F_SETLK, &value) } == -1 {
        let error = std::io::Error::last_os_error();
        if matches!(error.raw_os_error(), Some(libc::EACCES | libc::EAGAIN)) {
            return Err(Error::AlreadyRunning);
        }
        return Err(error.into());
    }
    Ok(())
}
fn owner(file: &File, start: i64) -> Result<Option<i32>, Error> {
    let mut value = request(libc::F_WRLCK as libc::c_short, start, 1);
    // SAFETY: value is writable flock storage matching this Linux ABI; F_GETLK
    // only inspects conflicts and does not acquire, change or release a lock.
    if unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETLK, &mut value) } == -1 {
        return Err(std::io::Error::last_os_error().into());
    }
    // Linux returns the complete conflicting lock range in this same snapshot.
    // Before publication our lock is [0,2); afterwards it is exactly [0,1).
    // Separate byte-0/byte-1 probes alone could combine different failed
    // initializers when both owners are invisible (l_pid=0). Reject the init
    // range atomically, even if its process exits before our next syscall.
    if start == 0
        && value.l_type != libc::F_UNLCK as libc::c_short
        && (value.l_type != libc::F_WRLCK as libc::c_short
            || value.l_start != 0
            || value.l_len != 1)
    {
        return Err(Error::NotReady);
    }
    // A lock held outside our PID namespace is present even when l_pid is 0.
    Ok((value.l_type != libc::F_UNLCK as libc::c_short).then_some(value.l_pid))
}
fn bytes(file: &mut File) -> Result<Vec<u8>, Error> {
    file.seek(SeekFrom::Start(0))?;
    let mut result = Vec::new();
    file.take(MAX_RECORD + 1).read_to_end(&mut result)?;
    if result.len() as u64 > MAX_RECORD {
        return Err(Error::InvalidState);
    }
    Ok(result)
}
fn parse(data: &[u8]) -> Result<Record, Error> {
    let text = std::str::from_utf8(data).map_err(|_| Error::InvalidState)?;
    let fields: Vec<_> = text.split_whitespace().collect();
    if fields.len() != 3 || fields[0] != MAGIC {
        return Err(Error::InvalidState);
    }
    let pid = fields[1].parse::<i32>().map_err(|_| Error::InvalidState)?;
    let start_ns = fields[2].parse::<u64>().map_err(|_| Error::InvalidState)?;
    if pid <= 0 {
        return Err(Error::InvalidState);
    }
    Ok(Record { pid, start_ns })
}
impl Session {
    pub(crate) fn acquire(path: &Path) -> Result<Self, Error> {
        // Do not use O_CREAT for existing files: sticky-/tmp protected_regular
        // rules must not prohibit another login user from opening this inode.
        let mut file = loop {
            match OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
                .open(path)
            {
                Ok(file) => break file,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    match OpenOptions::new()
                        .read(true)
                        .write(true)
                        .create_new(true)
                        .mode(0o666)
                        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
                        .open(path)
                    {
                        Ok(file) => {
                            file.set_permissions(Permissions::from_mode(0o666))?;
                            break file;
                        }
                        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                        Err(error) => return Err(error.into()),
                    }
                }
                Err(error) => return Err(error.into()),
            }
        };
        check_file(&file)?;
        // Byte 0 holds the singleton; byte 1 marks initialization. Unlock only
        // byte 1 after publication, preserving byte 0 for the session lifetime.
        set_lock(&file, libc::F_WRLCK as libc::c_short, 0, 2)?;
        let previous = bytes(&mut file)?;
        if !previous.is_empty() {
            parse(&previous)?;
        }
        Ok(Self {
            file,
            record: Record {
                pid: std::process::id() as i32,
                start_ns: 0,
            },
        })
    }
    pub(crate) fn publish(&mut self) -> Result<(), Error> {
        self.record.start_ns = clock::now_ns()?;
        let record = format!("{MAGIC} {} {}\n", self.record.pid, self.record.start_ns);
        self.file.seek(SeekFrom::Start(0))?;
        self.file.set_len(0)?;
        self.file.write_all(record.as_bytes())?;
        set_lock(&self.file, libc::F_UNLCK as libc::c_short, 1, 1)
    }
}
pub(crate) fn query_record(path: &Path) -> Result<Record, Error> {
    let mut file = match OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
    {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Err(Error::NotRunning);
        }
        Err(error) => return Err(error.into()),
    };
    check_file(&file)?;
    let first_owner = owner(&file, 0)?.ok_or(Error::NotRunning)?;
    if owner(&file, 1)?.is_some() {
        return Err(Error::NotReady);
    }
    let first = bytes(&mut file)?;
    let second_owner = owner(&file, 0)?.ok_or(Error::NotRunning)?;
    if first_owner != second_owner || owner(&file, 1)?.is_some() {
        return Err(Error::NotReady);
    }
    let second = bytes(&mut file)?;
    if first != second {
        return Err(Error::NotReady);
    }
    // The record PID belongs to the publisher's namespace; F_GETLK translates
    // its owner into the reader's namespace (possibly 0). They are not identity
    // values that can be compared. The initialization lock protects publication,
    // and the checks above require a live lock and an unchanged complete record.
    parse(&first)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        fs,
        io::{BufRead, BufReader, Write},
        os::unix::{
            ffi::OsStrExt,
            fs::{MetadataExt, symlink},
        },
        path::PathBuf,
        process::{Child, Command, Stdio},
        sync::atomic::{AtomicU64, Ordering},
    };
    static NEXT: AtomicU64 = AtomicU64::new(0);
    struct Temp(PathBuf);
    impl Temp {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "fff-timer-unit-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir(&path).unwrap();
            Self(path)
        }
        fn state(&self) -> PathBuf {
            self.0.join("state")
        }
    }
    impl Drop for Temp {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    struct Holder {
        child: Child,
        output: BufReader<std::process::ChildStdout>,
    }
    impl Holder {
        fn new(path: &Path) -> Self {
            Self::spawn(path, false)
        }
        fn spawn(path: &Path, in_namespace: bool) -> Self {
            let mut command = if in_namespace {
                namespace_command()
            } else {
                Command::new(std::env::current_exe().unwrap())
            };
            let mut child = command
                .args(["--exact", "state::tests::holder_child", "--nocapture"])
                .env("FFF_TIMER_UNIT_STATE", path)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .spawn()
                .unwrap();
            let output = BufReader::new(child.stdout.take().unwrap());
            let mut holder = Self { child, output };
            holder.until("LOCKED");
            holder
        }
        fn until(&mut self, marker: &str) {
            loop {
                let mut line = String::new();
                assert_ne!(
                    self.output.read_line(&mut line).unwrap(),
                    0,
                    "child exited before {marker}"
                );
                if line.trim() == marker {
                    break;
                }
            }
        }
        fn publish(&mut self) {
            writeln!(self.child.stdin.as_mut().unwrap(), "publish").unwrap();
            self.until("PUBLISHED");
        }
        fn stop(&mut self) {
            writeln!(self.child.stdin.as_mut().unwrap(), "exit").unwrap();
            assert!(self.child.wait().unwrap().success());
        }
    }
    impl Drop for Holder {
        fn drop(&mut self) {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
    #[test]
    fn holder_child() {
        let Some(path) = std::env::var_os("FFF_TIMER_UNIT_STATE") else {
            return;
        };
        let mut session = Session::acquire(Path::new(&path)).unwrap();
        println!("LOCKED");
        std::io::stdout().flush().unwrap();
        for line in std::io::stdin().lock().lines() {
            match line.unwrap().as_str() {
                "publish" => {
                    session.publish().unwrap();
                    println!("PUBLISHED");
                    std::io::stdout().flush().unwrap();
                }
                "exit" => break,
                _ => panic!("unknown test command"),
            }
        }
    }
    fn namespace_command() -> Command {
        let mut command = Command::new("unshare");
        command
            .args([
                "--user",
                "--map-root-user",
                "--pid",
                "--fork",
                "--mount-proc",
                "--kill-child=KILL",
            ])
            .arg(std::env::current_exe().unwrap());
        command
    }
    fn can_create_namespace() -> bool {
        let output = Command::new("unshare")
            .args([
                "--user",
                "--map-root-user",
                "--pid",
                "--fork",
                "--mount-proc",
                "true",
            ])
            .output();
        match output {
            Ok(output) if output.status.success() => true,
            Ok(output)
                if String::from_utf8_lossy(&output.stderr).contains("Operation not permitted")
                    || String::from_utf8_lossy(&output.stderr).contains("Permission denied") =>
            {
                eprintln!(
                    "SKIP PID namespace regression: {}",
                    String::from_utf8_lossy(&output.stderr)
                );
                false
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                eprintln!("SKIP PID namespace regression: {error}");
                false
            }
            other => panic!("unexpected namespace probe failure: {other:?}"),
        }
    }
    #[test]
    fn namespace_query_child() {
        let Some(path) = std::env::var_os("FFF_TIMER_UNIT_QUERY_STATE") else {
            return;
        };
        let path = Path::new(&path);
        let file = File::open(path).unwrap();
        assert_eq!(
            owner(&file, 0).unwrap(),
            Some(0),
            "ancestor lock must be present with invisible PID"
        );
        assert!(query_record(path).unwrap().start_ns > 0);
    }
    #[test]
    fn child_namespace_can_query_a_live_ancestor_lock() {
        if !can_create_namespace() {
            return;
        }
        let temp = Temp::new();
        let path = temp.state();
        let mut holder = Holder::new(&path);
        holder.publish();
        let before = fs::read(&path).unwrap();
        let meta = fs::metadata(&path).unwrap();
        let output = namespace_command()
            .args([
                "--exact",
                "state::tests::namespace_query_child",
                "--nocapture",
            ])
            .env("FFF_TIMER_UNIT_QUERY_STATE", &path)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}\n{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(fs::read(&path).unwrap(), before);
        assert_eq!(
            fs::metadata(&path).unwrap().modified().unwrap(),
            meta.modified().unwrap()
        );
        assert!(matches!(
            Session::acquire(&path),
            Err(Error::AlreadyRunning)
        ));
        holder.stop();
        assert!(matches!(query_record(&path), Err(Error::NotRunning)));
        println!("PASS: real child namespace query, l_pid=0, read-only and singleton preserved");
    }
    #[test]
    fn ancestor_can_query_a_live_child_with_remapped_positive_pid() {
        if !can_create_namespace() {
            return;
        }
        let temp = Temp::new();
        let path = temp.state();
        let mut holder = Holder::spawn(&path, true);
        assert!(matches!(query_record(&path), Err(Error::NotReady)));
        holder.publish();
        let mut file = File::open(&path).unwrap();
        let recorded = parse(&bytes(&mut file).unwrap()).unwrap();
        let mapped = owner(&file, 0).unwrap().unwrap();
        assert!(mapped > 0 && mapped != recorded.pid);
        assert_eq!(query_record(&path).unwrap(), recorded);
        holder.stop();
        assert!(matches!(query_record(&path), Err(Error::NotRunning)));
        println!(
            "PASS: real ancestor namespace query, remapped positive PID and stale-state rejection"
        );
    }
    #[test]
    fn published_record_pid_is_diagnostic_not_a_lock_identity() {
        let temp = Temp::new();
        let path = temp.state();
        let mut holder = Holder::new(&path);
        holder.publish();
        let record = query_record(&path).unwrap();
        // The same valid record can contain the holder's PID as seen from
        // another namespace. This fixture covers the policy even when the
        // test environment forbids creating a real namespace.
        fs::write(&path, format!("FFF_TIMER_V1 1 {}\n", record.start_ns)).unwrap();
        let actual = query_record(&path).unwrap();
        assert_eq!(
            actual,
            Record {
                pid: 1,
                start_ns: record.start_ns
            }
        );
        holder.stop();
        assert!(matches!(query_record(&path), Err(Error::NotRunning)));
    }
    #[test]
    fn only_one_process_can_start_and_query_is_read_only() {
        let temp = Temp::new();
        let path = temp.state();
        let mut holder = Holder::new(&path);
        assert!(matches!(query_record(&path), Err(Error::NotReady)));
        assert!(matches!(
            Session::acquire(&path),
            Err(Error::AlreadyRunning)
        ));
        holder.publish();
        let before = fs::read(&path).unwrap();
        let meta = fs::metadata(&path).unwrap();
        let record = query_record(&path).unwrap();
        assert_eq!(record.pid, holder.child.id() as i32);
        assert!(record.start_ns > 0);
        for _ in 0..5 {
            assert_eq!(query_record(&path).unwrap(), record);
        }
        assert_eq!(fs::read(&path).unwrap(), before);
        assert_eq!(
            fs::metadata(&path).unwrap().modified().unwrap(),
            meta.modified().unwrap()
        );
        assert_eq!(meta.mode() & 0o777, 0o666);
        assert!(matches!(
            Session::acquire(&path),
            Err(Error::AlreadyRunning)
        ));
        holder.stop();
        assert!(matches!(query_record(&path), Err(Error::NotRunning)));
        assert!(path.exists());
    }
    #[test]
    fn stale_record_is_not_alive_and_restart_has_a_new_origin() {
        let temp = Temp::new();
        let path = temp.state();
        let mut first = Holder::new(&path);
        first.publish();
        let old = query_record(&path).unwrap();
        first.child.kill().unwrap();
        first.child.wait().unwrap();
        assert!(matches!(query_record(&path), Err(Error::NotRunning)));
        let mut second = Holder::new(&path);
        assert!(matches!(query_record(&path), Err(Error::NotReady)));
        second.publish();
        let new = query_record(&path).unwrap();
        assert!(new.start_ns > old.start_ns);
        second.stop();
    }
    #[test]
    fn reused_pid_cannot_expose_an_old_origin_while_initializing() {
        let temp = Temp::new();
        let path = temp.state();
        let mut holder = Holder::new(&path);
        // Simulate a stale record whose PID happens to match the new process.
        // This is test fixture setup, never an operation performed by query.
        fs::write(&path, format!("FFF_TIMER_V1 {} 1\n", holder.child.id())).unwrap();
        assert!(matches!(query_record(&path), Err(Error::NotReady)));
        holder.publish();
        assert!(query_record(&path).unwrap().start_ns > 1);
        holder.stop();
    }

    #[test]
    fn querying_absent_timer_does_not_create_files() {
        let temp = Temp::new();
        let path = temp.state();
        assert!(matches!(query_record(&path), Err(Error::NotRunning)));
        assert!(!path.exists());
    }
    #[test]
    fn refuses_unknown_data_links_and_non_regular_files_without_changes() {
        let temp = Temp::new();
        let path = temp.state();
        fs::write(&path, b"unrelated data").unwrap();
        assert!(matches!(Session::acquire(&path), Err(Error::InvalidState)));
        assert_eq!(fs::read(&path).unwrap(), b"unrelated data");
        let link = temp.0.join("symlink");
        symlink(&path, &link).unwrap();
        assert!(Session::acquire(&link).is_err());
        assert!(query_record(&link).is_err());
        let hard = temp.0.join("hardlink");
        fs::hard_link(&path, &hard).unwrap();
        assert!(Session::acquire(&hard).is_err());
        let fifo = temp.0.join("fifo");
        let c = std::ffi::CString::new(fifo.as_os_str().as_bytes()).unwrap();
        // SAFETY: c is a valid NUL-terminated local test path; mkfifo retains no pointer.
        assert_eq!(unsafe { libc::mkfifo(c.as_ptr(), 0o600) }, 0);
        assert!(Session::acquire(&fifo).is_err());
        assert!(query_record(&fifo).is_err());
        assert_eq!(fs::read(&path).unwrap(), b"unrelated data");
    }
}
