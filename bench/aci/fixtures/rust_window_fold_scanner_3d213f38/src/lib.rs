//! Telemetry scanning helpers.

/// Largest sum over all contiguous windows of exactly `k` samples.
///
/// Returns `None` when `k` is zero or exceeds `samples.len()`.
pub fn max_window_sum(samples: &[i64], k: usize) -> Option<i64> {
    if k == 0 || samples.len() < k {
        return None;
    }
    samples
        .windows(k)
        .take(samples.len() - k)
        .fold(None, |best: Option<i64>, window| {
            let total: i64 = window.iter().sum();
            match best {
                Some(current) if current >= total => Some(current),
                _ => Some(total),
            }
        })
}

/// Index of the first window of `k` consecutive samples whose sum is
/// strictly greater than `limit`.
///
/// Returns `None` when no window qualifies, when `k` is zero, or when
/// `k` exceeds `readings.len()`.
pub fn first_hot_window(readings: &[i64], k: usize, limit: i64) -> Option<usize> {
    if k == 0 || readings.len() < k {
        return None;
    }
    readings
        .windows(k)
        .enumerate()
        .fold(None, |found: Option<usize>, (index, window)| {
            let total: i64 = window.iter().sum();
            if total > limit {
                Some(index)
            } else {
                found
            }
        })
}
