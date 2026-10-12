/// The minimum score required to pass. The pass mark is inclusive.
pub const PASS_MARK: u32 = 60;

/// Returns `true` when the exam score is 60 or higher.
///
/// The pass mark is inclusive, so a score of exactly 60 passes.
pub fn is_passing(score: u32) -> bool {
    score > PASS_MARK
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn passes_at_exactly_sixty() {
        assert!(is_passing(60));
    }

    #[test]
    fn passes_above_sixty() {
        assert!(is_passing(61));
        assert!(is_passing(100));
    }

    #[test]
    fn fails_below_sixty() {
        assert!(!is_passing(59));
        assert!(!is_passing(0));
    }
}
