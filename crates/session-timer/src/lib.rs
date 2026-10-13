mod clock;
mod state;

#[derive(Debug)]
pub enum Error {
    NotRunning,
    AlreadyRunning,
    NotReady,
    InvalidState,
    Io(std::io::Error),
}
impl From<std::io::Error> for Error {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}
