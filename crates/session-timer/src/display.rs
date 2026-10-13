use std::{
    fs::{File, OpenOptions},
    io::{IsTerminal, Write},
    os::{fd::AsRawFd, unix::fs::OpenOptionsExt},
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Size {
    pub cols: usize,
    pub rows: usize,
}
const DIGITS: [[&str; 7]; 10] = [
    [
        "01110", "10001", "10001", "10001", "10001", "10001", "01110",
    ],
    [
        "00100", "01100", "00100", "00100", "00100", "00100", "01110",
    ],
    [
        "01110", "10001", "00001", "00010", "00100", "01000", "11111",
    ],
    [
        "11110", "00001", "00001", "01110", "00001", "00001", "11110",
    ],
    [
        "00010", "00110", "01010", "10010", "11111", "00010", "00010",
    ],
    [
        "11111", "10000", "10000", "11110", "00001", "00001", "11110",
    ],
    [
        "01110", "10000", "10000", "11110", "10001", "10001", "01110",
    ],
    [
        "11111", "00001", "00010", "00100", "01000", "01000", "01000",
    ],
    [
        "01110", "10001", "10001", "01110", "10001", "10001", "01110",
    ],
    [
        "01110", "10001", "10001", "01111", "00001", "00001", "01110",
    ],
];
pub(crate) fn raster(text: &str, size: Size) -> Option<Vec<String>> {
    if text.len() != 8
        || !text.bytes().enumerate().all(|(i, c)| {
            if i == 2 || i == 5 {
                c == b':'
            } else {
                c.is_ascii_digit()
            }
        })
    {
        return None;
    }
    let horizontal = (size.cols.saturating_sub(2) / 39).min(32);
    let vertical = (size.rows.saturating_sub(2) / 7)
        .min(horizontal.div_ceil(2))
        .min(16);
    if horizontal == 0 || vertical == 0 {
        return None;
    }
    let mut rows = Vec::new();
    for (row, colon) in ["0", "0", "1", "0", "1", "0", "0"].iter().enumerate() {
        let mut line = String::new();
        for (index, c) in text.bytes().enumerate() {
            if index > 0 {
                line.push_str(&" ".repeat(horizontal));
            }
            let bits = if c == b':' {
                colon
            } else {
                DIGITS[(c - b'0') as usize][row]
            };
            for bit in bits.bytes() {
                line.push_str(&if bit == b'1' { "█" } else { " " }.repeat(horizontal));
            }
        }
        for _ in 0..vertical {
            rows.push(line.clone());
        }
    }
    Some(rows)
}
pub(crate) fn frame(text: &str, size: Option<Size>, ansi: bool) -> String {
    if !ansi {
        return format!("\r{text}");
    }
    let mut result = String::from("\x1b[H\x1b[2J");
    if let Some((size, rows)) = size.and_then(|s| raster(text, s).map(|r| (s, r))) {
        let top = (size.rows - rows.len()) / 2 + 1;
        let left = (size.cols - rows[0].chars().count()) / 2 + 1;
        for (row, line) in rows.iter().enumerate() {
            result.push_str(&format!("\x1b[{};{}H{}", top + row, left, line));
        }
    } else {
        result.push_str(text);
    }
    result
}
fn dimensions(file: &File) -> Option<Size> {
    let mut size = libc::winsize {
        ws_row: 0,
        ws_col: 0,
        ws_xpixel: 0,
        ws_ypixel: 0,
    };
    // SAFETY: size is valid writable winsize storage; ioctl retains no pointer.
    if unsafe { libc::ioctl(file.as_raw_fd(), libc::TIOCGWINSZ, &mut size) } == 0
        && size.ws_col > 0
        && size.ws_row > 0
    {
        Some(Size {
            cols: size.ws_col.into(),
            rows: size.ws_row.into(),
        })
    } else {
        None
    }
}
pub(crate) struct Terminal {
    output: Option<File>,
    ansi: bool,
    entered: bool,
    pending: Vec<u8>,
    offset: usize,
    last: Option<(String, Option<Size>)>,
}
impl Terminal {
    pub(crate) fn new() -> Self {
        // Reopening our own terminal gives an independent open-file description.
        // O_NONBLOCK must not modify the shell's inherited stdout flags.
        let output = if std::io::stdout().is_terminal() {
            OpenOptions::new()
                .write(true)
                .custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY)
                .open("/proc/self/fd/1")
                .ok()
        } else {
            None
        };
        let ansi = std::env::var("TERM").is_ok_and(|term| !term.is_empty() && term != "dumb");
        Self {
            output,
            ansi,
            entered: false,
            pending: Vec::new(),
            offset: 0,
            last: None,
        }
    }
    fn drain(&mut self) {
        for _ in 0..4 {
            let Some(file) = self.output.as_mut() else {
                return;
            };
            if self.offset == self.pending.len() {
                self.pending.clear();
                self.offset = 0;
                return;
            }
            match file.write(&self.pending[self.offset..]) {
                Ok(0) => {
                    self.output = None;
                    return;
                }
                Ok(count) => self.offset += count,
                Err(error)
                    if matches!(
                        error.kind(),
                        std::io::ErrorKind::WouldBlock | std::io::ErrorKind::Interrupted
                    ) =>
                {
                    return;
                }
                Err(_) => {
                    self.output = None;
                    return;
                }
            }
        }
    }
    pub(crate) fn update(&mut self, text: &str) {
        self.drain();
        if self.offset < self.pending.len() {
            return;
        }
        let Some(file) = self.output.as_ref() else {
            return;
        };
        let size = dimensions(file);
        let key = (text.to_owned(), size);
        if self.last.as_ref() == Some(&key) {
            return;
        }
        let mut output = String::new();
        if self.ansi && !self.entered {
            output.push_str("\x1b[?1049h\x1b[?25l");
            self.entered = true;
        }
        output.push_str(&frame(text, size, self.ansi));
        self.last = Some(key);
        self.pending = output.into_bytes();
        self.offset = 0;
        self.drain();
    }
    pub(crate) fn finish(&mut self) {
        if let Some(mut file) = self.output.take() {
            let text = if self.entered {
                "\x1b[?25h\x1b[?1049l"
            } else {
                "\n"
            };
            // Discard unfinished drawing, then give a temporarily full terminal
            // a bounded opportunity to accept the complete restoration sequence.
            let deadline = std::time::Instant::now() + std::time::Duration::from_millis(250);
            let mut offset = 0;
            while offset < text.len() && std::time::Instant::now() < deadline {
                match file.write(&text.as_bytes()[offset..]) {
                    Ok(0) => break,
                    Ok(count) => offset += count,
                    Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        let remaining =
                            deadline.saturating_duration_since(std::time::Instant::now());
                        let timeout = remaining.as_millis().clamp(1, 250) as libc::c_int;
                        let mut descriptor = libc::pollfd {
                            fd: file.as_raw_fd(),
                            events: libc::POLLOUT,
                            revents: 0,
                        };
                        // SAFETY: descriptor is valid writable pollfd storage,
                        // file keeps its fd alive, and the wait has a finite bound.
                        let result = unsafe { libc::poll(&mut descriptor, 1, timeout) };
                        if result < 0
                            && std::io::Error::last_os_error().kind()
                                != std::io::ErrorKind::Interrupted
                        {
                            break;
                        }
                        if descriptor.revents & (libc::POLLERR | libc::POLLHUP | libc::POLLNVAL)
                            != 0
                        {
                            break;
                        }
                    }
                    Err(_) => break,
                }
            }
        }
        self.entered = false;
        self.pending.clear();
        self.offset = 0;
    }
}
impl Drop for Terminal {
    fn drop(&mut self) {
        self.finish();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn finish_restores_terminal_when_output_drains_after_a_short_stall() {
        use std::{
            io::Read,
            os::fd::FromRawFd,
            time::{Duration, Instant},
        };
        let (mut master, mut slave) = (-1, -1);
        let size = libc::winsize {
            ws_row: 1000,
            ws_col: 2000,
            ws_xpixel: 0,
            ws_ypixel: 0,
        };
        // SAFETY: descriptor outputs and winsize are valid storage; optional
        // name/termios pointers may be null. Successful descriptors are owned below.
        assert_eq!(
            unsafe {
                libc::openpty(
                    &mut master,
                    &mut slave,
                    std::ptr::null_mut(),
                    std::ptr::null(),
                    &size,
                )
            },
            0
        );
        // SAFETY: openpty returned these distinct, uniquely owned descriptors.
        let mut reader = unsafe { File::from_raw_fd(master) };
        // SAFETY: slave is the other unique descriptor from openpty.
        let output = unsafe { File::from_raw_fd(slave) };
        // SAFETY: output owns this valid descriptor; these fcntl commands take
        // no pointer and only change this test's independently created PTY.
        let flags = unsafe { libc::fcntl(output.as_raw_fd(), libc::F_GETFL) };
        assert!(flags >= 0);
        // SAFETY: as above, setting the flags of our own valid descriptor.
        assert_eq!(
            unsafe { libc::fcntl(output.as_raw_fd(), libc::F_SETFL, flags | libc::O_NONBLOCK) },
            0
        );
        let mut terminal = Terminal {
            output: Some(output),
            ansi: true,
            entered: false,
            pending: Vec::new(),
            offset: 0,
            last: None,
        };
        terminal.update("00:00:00");
        let reading = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(50));
            let mut captured = Vec::new();
            let mut chunk = [0u8; 65536];
            loop {
                match reader.read(&mut chunk) {
                    Ok(0) => break,
                    Ok(count) => captured.extend_from_slice(&chunk[..count]),
                    Err(error) if error.raw_os_error() == Some(libc::EIO) => break,
                    Err(error) => panic!("PTY read failed: {error}"),
                }
            }
            captured
        });
        let started = Instant::now();
        terminal.finish();
        assert!(started.elapsed() < Duration::from_secs(1));
        let captured = reading.join().unwrap();
        assert!(captured.windows(8).any(|part| part == b"\x1b[?1049h"));
        assert!(
            captured.ends_with(b"\x1b[?25h\x1b[?1049l"),
            "missing complete cursor/screen restoration after temporary backpressure"
        );
    }

    #[test]
    fn large_clock_has_complete_scaled_glyphs_that_fit() {
        let rows = raster("12:34:56", Size { cols: 41, rows: 9 }).unwrap();
        assert_eq!(rows.len(), 7);
        assert!(rows.iter().all(|r| r.chars().count() == 39));
        assert_eq!(
            rows[0],
            [
                "  █  ",
                " ███ ",
                " ",
                "████ ",
                "   █ ",
                " ",
                "█████",
                " ███ "
            ]
            .join(" ")
        );
        let normal = raster("00:00:00", Size { cols: 80, rows: 24 }).unwrap();
        assert!(normal.iter().all(|r| r.chars().count() == 78));
        let wide = raster(
            "00:00:00",
            Size {
                cols: 160,
                rows: 40,
            },
        )
        .unwrap();
        assert_eq!(wide.len(), 14);
        assert!(wide.iter().all(|r| r.chars().count() == 156));
    }
    #[test]
    fn too_small_unknown_or_dumb_terminal_uses_basic_time() {
        assert!(raster("00:00:00", Size { cols: 40, rows: 24 }).is_none());
        assert!(raster("00:00:00", Size { cols: 80, rows: 8 }).is_none());
        for (size, ansi) in [
            (None, true),
            (Some(Size { cols: 20, rows: 4 }), true),
            (
                Some(Size {
                    cols: 160,
                    rows: 40,
                }),
                false,
            ),
        ] {
            let result = frame("12:34:56", size, ansi);
            assert!(result.contains("12:34:56"));
            assert!(!result.contains('█'));
            if !ansi {
                assert!(!result.contains('\x1b'));
            }
        }
    }
    #[test]
    fn positioned_frame_stays_inside_terminal_and_limits_allocation() {
        let result = frame("12:34:56", Some(Size { cols: 80, rows: 24 }), true);
        assert!(result.contains('█'));
        assert!(result.contains("\x1b[9;2H"));
        let huge = raster(
            "99:59:59",
            Size {
                cols: 65535,
                rows: 65535,
            },
        )
        .unwrap();
        assert!(huge.iter().map(String::len).sum::<usize>() < 512 * 1024);
    }
}
