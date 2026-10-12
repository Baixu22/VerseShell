use username::validate_username;

#[test]
fn test_accepts_valid_usernames() {
    for name in ["abc", "alice", "a123456789012345", "x_x-x", "Zed9"] {
        assert!(validate_username(name).is_ok(), "expected Ok for {:?}", name);
    }
}

#[test]
fn test_rejects_too_short() {
    assert!(validate_username("").is_err());
    assert!(validate_username("ab").is_err());
}

#[test]
fn test_rejects_too_long() {
    assert!(validate_username("a1234567890123456").is_err());
}

#[test]
fn test_rejects_whitespace() {
    assert!(validate_username("ab c").is_err());
    assert!(validate_username("abc\t").is_err());
    assert!(validate_username(" abc").is_err());
}

#[test]
fn test_rejects_non_letter_start() {
    assert!(validate_username("1abc").is_err());
    assert!(validate_username("_abc").is_err());
    assert!(validate_username("-abc").is_err());
}
