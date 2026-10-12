use config_kit::{parse_duration, read_config, ParseError};
use std::error::Error;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};

static NEXT_ID: AtomicUsize = AtomicUsize::new(0);

fn temp_config(contents: &str) -> PathBuf {
    let id = NEXT_ID.fetch_add(1, Ordering::SeqCst);
    let mut path = std::env::temp_dir();
    path.push(format!("config_kit_test_{}_{}.cfg", std::process::id(), id));
    let mut file = fs::File::create(&path).unwrap();
    file.write_all(contents.as_bytes()).unwrap();
    path
}

#[test]
fn parse_duration_happy_path() {
    assert_eq!(parse_duration("45s").unwrap(), 45);
}

#[test]
fn parse_duration_reports_bad_input_instead_of_panicking() {
    let err = parse_duration("12x").unwrap_err();
    assert!(matches!(err, ParseError::NotANumber), "got {:?}", err);
}

#[test]
fn read_config_returns_value() {
    let path = temp_config("retries=3\nname = grid\n");
    let value = read_config(path.to_str().unwrap(), "name").unwrap();
    assert_eq!(value, "grid");
    let _ = fs::remove_file(&path);
}

#[test]
fn missing_key_is_reported() {
    let path = temp_config("retries=3\n");
    let err = read_config(path.to_str().unwrap(), "timeout").unwrap_err();
    assert!(matches!(err, config_kit::LoadError::MissingKey), "got {:?}", err);
    let _ = fs::remove_file(&path);
}

#[test]
fn io_error_source_is_preserved() {
    let err = read_config("definitely/missing/config.cfg", "name").unwrap_err();
    let source = err
        .source()
        .expect("LoadError must expose the underlying io error as its source");
    let io_err = source
        .downcast_ref::<std::io::Error>()
        .expect("source should be the original std::io::Error");
    assert_eq!(io_err.kind(), std::io::ErrorKind::NotFound);
}
