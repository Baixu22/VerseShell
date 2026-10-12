/// Returns the longest whitespace-separated word in `input`.
/// The returned slice must borrow from `input` and never allocate.
pub fn longest_word(input: &str) -> &str {
    let mut best = "";
    for word in input.split_whitespace() {
        if word.len() > best.len() {
            best = word;
        }
    }
    best
}
