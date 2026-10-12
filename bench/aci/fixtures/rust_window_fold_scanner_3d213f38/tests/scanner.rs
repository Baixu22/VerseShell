use scanner::{first_hot_window, max_window_sum};

#[test]
fn max_window_sum_uses_every_full_window() {
    // windows of 2 over [1, 2, 3]: [1, 2] = 3, [2, 3] = 5
    assert_eq!(max_window_sum(&[1, 2, 3], 2), Some(5));
}

#[test]
fn max_window_sum_accepts_a_window_covering_the_whole_slice() {
    assert_eq!(max_window_sum(&[4, -1, 7], 3), Some(10));
}

#[test]
fn max_window_sum_prefers_the_trailing_window_for_negative_samples() {
    // windows of 1: -5, -3, -1
    assert_eq!(max_window_sum(&[-5, -3, -1], 1), Some(-1));
}

#[test]
fn max_window_sum_rejects_degenerate_window_sizes() {
    assert_eq!(max_window_sum(&[1, 2, 3], 0), None);
    assert_eq!(max_window_sum(&[1, 2, 3], 4), None);
}

#[test]
fn first_hot_window_reports_the_earliest_hot_window() {
    // windows of 1 over [1, 9, 9, 1]: hot at indices 1 and 2
    assert_eq!(first_hot_window(&[1, 9, 9, 1], 1, 5), Some(1));
}

#[test]
fn first_hot_window_can_match_at_index_zero() {
    assert_eq!(first_hot_window(&[9, 1, 1], 1, 5), Some(0));
}

#[test]
fn first_hot_window_scans_multi_sample_windows() {
    // windows of 2 over [0, 3, 3, 0, 6]: sums 3, 6, 3, 6 -> first hot at 1
    assert_eq!(first_hot_window(&[0, 3, 3, 0, 6], 2, 5), Some(1));
}

#[test]
fn first_hot_window_returns_none_when_nothing_is_hot() {
    assert_eq!(first_hot_window(&[1, 2, 3], 2, 100), None);
}

#[test]
fn first_hot_window_rejects_degenerate_window_sizes() {
    assert_eq!(first_hot_window(&[1, 2, 3], 0, 0), None);
    assert_eq!(first_hot_window(&[1, 2, 3], 4, 0), None);
}
