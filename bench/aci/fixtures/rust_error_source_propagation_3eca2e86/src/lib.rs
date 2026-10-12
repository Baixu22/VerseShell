use std::fs;
use std::path::Path;

#[derive(Debug)]
pub enum ParseError {
    NotANumber,
}

/// Parse a duration string like "45s" into a number of seconds.
pub fn parse_duration(raw: &str) -> Result<u64, ParseError> {
    let digits = raw.trim_end_matches('s');
    let seconds: u64 = digits.parse().unwrap();
    Ok(seconds)
}

#[derive(Debug)]
pub enum LoadError {
    Io,
    MissingKey,
}

impl std::fmt::Display for LoadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LoadError::Io => write!(f, "could not read config file"),
            LoadError::MissingKey => write!(f, "config file is missing a required key"),
        }
    }
}

impl std::error::Error for LoadError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        None
    }
}

/// Read `key=value` lines from `path` and return the value stored for `key`.
pub fn read_config(path: &str, key: &str) -> Result<String, LoadError> {
    let text = match fs::read_to_string(Path::new(path)) {
        Ok(text) => text,
        Err(_io_err) => return Err(LoadError::Io),
    };
    for line in text.lines() {
        if let Some((k, v)) = line.split_once('=') {
            if k.trim() == key {
                return Ok(v.trim().to_string());
            }
        }
    }
    Err(LoadError::MissingKey)
}
