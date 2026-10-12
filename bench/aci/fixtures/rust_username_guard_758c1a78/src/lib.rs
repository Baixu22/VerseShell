//! Username validation.
//!
//! A valid username is 3–16 characters long, contains no whitespace,
//! and starts with a letter.

/// Validate a username.
///
/// Returns `Ok(())` if the username is between 3 and 16 characters long
/// (inclusive), contains no whitespace, and starts with a letter.
/// Otherwise returns `Err` with a message describing the problem.
pub fn validate_username(username: &str) -> Result<(), String> {
    let len = username.chars().count();

    if !(3..=16).contains(&len) {
        return Err(format!(
            "username must be between 3 and 16 characters long (got {})",
            len
        ));
    }

    if username.chars().all(|c| !c.is_whitespace()) {
        return Err("username must not contain whitespace".to_string());
    }

    match username.chars().next() {
        Some(c) if c.is_alphabetic() => Ok(()),
        _ => Err("username must start with a letter".to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::validate_username;

    #[test]
    fn accepts_valid_usernames() {
        for name in ["abc", "alice", "a123456789012345", "x_x-x"] {
            assert!(validate_username(name).is_ok(), "expected Ok for {:?}", name);
        }
    }

    #[test]
    fn rejects_too_short() {
        assert!(validate_username("").is_err());
        assert!(validate_username("ab").is_err());
    }

    #[test]
    fn rejects_too_long() {
        assert!(validate_username("a1234567890123456").is_err());
    }

    #[test]
    fn rejects_whitespace() {
        assert!(validate_username("ab c").is_err());
        assert!(validate_username("abc\t").is_err());
        assert!(validate_username(" abc").is_err());
    }

    #[test]
    fn rejects_non_letter_start() {
        assert!(validate_username("1abc").is_err());
        assert!(validate_username("_abc").is_err());
    }
}
