//! Small helper module for reading a port number from configuration.

/// Port returned when the configured value is absent or invalid.
const DEFAULT_PORT: u16 = 8080;

/// Parses the port from the config value string.
///
/// Returns `8080` as the default when the value is absent (`None`)
/// or is not a valid `u16`.
///
/// # Examples
///
/// - `parse_port(Some("3000"))` -> `3000`
/// - `parse_port(None)` -> `8080`
/// - `parse_port(Some("hello"))` -> `8080`
/// - `parse_port(Some("70000"))` -> `8080` (out of `u16` range)
pub fn parse_port(value: Option<&str>) -> u16 {
    match value {
        Some(raw) => raw.parse::<u16>().unwrap_or(DEFAULT_PORT),
        None => DEFAULT_PORT,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_valid_port() {
        assert_eq!(parse_port(Some("3000")), 3000);
        assert_eq!(parse_port(Some("80")), 80);
        assert_eq!(parse_port(Some("65535")), 65535);
    }

    #[test]
    fn defaults_when_absent() {
        assert_eq!(parse_port(None), DEFAULT_PORT);
        assert_eq!(parse_port(None), 8080);
    }

    #[test]
    fn defaults_when_invalid() {
        assert_eq!(parse_port(Some("")), 8080);
        assert_eq!(parse_port(Some("not-a-port")), 8080);
        assert_eq!(parse_port(Some("-1")), 8080);
        assert_eq!(parse_port(Some("70000")), 8080);
        assert_eq!(parse_port(Some("3.5")), 8080);
        assert_eq!(parse_port(Some(" 8080")), 8080);
    }
}
