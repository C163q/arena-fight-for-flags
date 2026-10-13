use crate::Error;

pub(crate) fn now_ns() -> Result<u64, Error> {
    let mut value = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: value is writable timespec storage; clock_gettime retains no pointer.
    if unsafe { libc::clock_gettime(libc::CLOCK_BOOTTIME, &mut value) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let seconds = u64::try_from(value.tv_sec).map_err(|_| Error::InvalidState)?;
    let nanos = u64::try_from(value.tv_nsec).map_err(|_| Error::InvalidState)?;
    seconds
        .checked_mul(1_000_000_000)
        .and_then(|v| v.checked_add(nanos))
        .ok_or(Error::InvalidState)
}
pub(crate) fn format_elapsed(start: u64, now: u64) -> Result<String, Error> {
    let seconds = (now.checked_sub(start).ok_or(Error::InvalidState)? / 1_000_000_000).min(359_999);
    Ok(format!(
        "{:02}:{:02}:{:02}",
        seconds / 3600,
        seconds / 60 % 60,
        seconds % 60
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn formats_elapsed_whole_seconds_and_saturates_without_wrapping() {
        for (seconds, want) in [
            (0, "00:00:00"),
            (59, "00:00:59"),
            (60, "00:01:00"),
            (3599, "00:59:59"),
            (3600, "01:00:00"),
            (359999, "99:59:59"),
            (360000, "99:59:59"),
        ] {
            assert_eq!(
                format_elapsed(
                    1_250_000_000,
                    1_250_000_000 + seconds * 1_000_000_000 + 999_999_999
                )
                .unwrap(),
                want
            );
        }
        assert_eq!(format_elapsed(0, u64::MAX).unwrap(), "99:59:59");
        assert!(matches!(format_elapsed(2, 1), Err(Error::InvalidState)));
    }
    #[test]
    fn boot_clock_is_positive_and_monotonic() {
        let before = now_ns().unwrap();
        assert!(before > 0);
        assert!(now_ns().unwrap() >= before);
    }
}
