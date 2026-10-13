use fff_ai_abi::*;
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use std::{
    io::{self, Read, Write},
    os::unix::net::UnixStream,
    time::Instant,
};
pub const MAX_MESSAGE: usize = 262_144;
#[derive(Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Request {
    Init {
        init: CtfInit,
    },
    Decide {
        request_id: u64,
        observation: ObservationData,
    },
    Shutdown,
}
#[derive(Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Response {
    Ready {
        abi_version: u32,
    },
    Decision {
        request_id: u64,
        status: i32,
        output: CtfTeamAction,
    },
    Error {
        message: String,
    },
    Bye,
}
fn remaining(deadline: Instant) -> io::Result<std::time::Duration> {
    let left = deadline.saturating_duration_since(Instant::now());
    if left.is_zero() {
        Err(io::Error::new(io::ErrorKind::TimedOut, "deadline exceeded"))
    } else {
        Ok(left)
    }
}
fn read_part(stream: &mut UnixStream, buffer: &mut [u8], deadline: Instant) -> io::Result<()> {
    let mut offset = 0;
    while offset < buffer.len() {
        stream.set_read_timeout(Some(remaining(deadline)?))?;
        match stream.read(&mut buffer[offset..]) {
            Ok(0) => {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "worker closed socket",
                ));
            }
            Ok(n) => offset += n,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
    remaining(deadline)?;
    Ok(())
}
pub fn send<T: Serialize>(stream: &mut UnixStream, value: &T, deadline: Instant) -> io::Result<()> {
    let payload = serde_json::to_vec(value).map_err(io::Error::other)?;
    if payload.len() > MAX_MESSAGE {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "message exceeds limit",
        ));
    }
    let mut buffer = Vec::with_capacity(payload.len() + 4);
    buffer.extend_from_slice(&(payload.len() as u32).to_le_bytes());
    buffer.extend(payload);
    let mut offset = 0;
    while offset < buffer.len() {
        stream.set_write_timeout(Some(remaining(deadline)?))?;
        match stream.write(&buffer[offset..]) {
            Ok(0) => {
                return Err(io::Error::new(
                    io::ErrorKind::WriteZero,
                    "closed worker socket",
                ));
            }
            Ok(n) => offset += n,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
    remaining(deadline)?;
    Ok(())
}
pub fn receive<T: DeserializeOwned>(stream: &mut UnixStream, deadline: Instant) -> io::Result<T> {
    let mut header = [0; 4];
    read_part(stream, &mut header, deadline)?;
    let len = u32::from_le_bytes(header) as usize;
    if len > MAX_MESSAGE {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "message exceeds limit",
        ));
    }
    let mut payload = vec![0; len];
    read_part(stream, &mut payload, deadline)?;
    let value = serde_json::from_slice(&payload)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    remaining(deadline)?;
    Ok(value)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn oversized_header_is_rejected_before_allocating_payload() {
        let (mut a, mut b) = UnixStream::pair().unwrap();
        a.write_all(&((MAX_MESSAGE + 1) as u32).to_le_bytes())
            .unwrap();
        let result: io::Result<Response> = receive(
            &mut b,
            Instant::now() + std::time::Duration::from_millis(50),
        );
        assert_eq!(result.err().unwrap().kind(), io::ErrorKind::InvalidData);
    }
}
