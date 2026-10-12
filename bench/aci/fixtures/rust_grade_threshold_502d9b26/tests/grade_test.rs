use grade::is_passing;

#[test]
fn test_passes_at_exactly_sixty() {
    // The pass mark is inclusive: exactly 60 passes.
    assert!(is_passing(60));
}

#[test]
fn test_passes_above_sixty() {
    assert!(is_passing(61));
    assert!(is_passing(100));
}

#[test]
fn test_fails_below_sixty() {
    assert!(!is_passing(59));
    assert!(!is_passing(1));
}

#[test]
fn test_fails_at_zero() {
    assert!(!is_passing(0));
}
