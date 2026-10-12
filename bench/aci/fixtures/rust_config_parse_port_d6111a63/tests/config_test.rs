use config::parse_port;

#[test]
fn test_parses_valid_port() {
    assert_eq!(parse_port(Some("3000")), 3000);
    assert_eq!(parse_port(Some("80")), 80);
    assert_eq!(parse_port(Some("0")), 0);
    assert_eq!(parse_port(Some("8080")), 8080);
    assert_eq!(parse_port(Some("65535")), 65535);
}

#[test]
fn test_defaults_when_absent() {
    assert_eq!(parse_port(None), 8080);
}

#[test]
fn test_defaults_when_invalid() {
    assert_eq!(parse_port(Some("")), 8080);
    assert_eq!(parse_port(Some("not-a-port")), 8080);
    assert_eq!(parse_port(Some("-1")), 8080);
    assert_eq!(parse_port(Some("3.5")), 8080);
    assert_eq!(parse_port(Some(" 8080")), 8080);
    assert_eq!(parse_port(Some("8080 ")), 8080);
}

#[test]
fn test_defaults_when_out_of_range() {
    assert_eq!(parse_port(Some("65536")), 8080);
    assert_eq!(parse_port(Some("70000")), 8080);
    assert_eq!(parse_port(Some("99999999999999999999")), 8080);
}
