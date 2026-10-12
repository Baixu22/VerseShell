use textlib::longest_word;

#[test]
fn picks_the_longest_word() {
    assert_eq!(longest_word("the quick brown fox jumped"), "jumped");
}

#[test]
fn ties_keep_the_first_occurrence() {
    assert_eq!(longest_word("aa bb"), "aa");
    assert_eq!(longest_word("one two"), "one");
}

#[test]
fn empty_input_yields_empty_slice() {
    assert_eq!(longest_word(""), "");
}

#[test]
fn result_borrows_from_input_instead_of_cloning() {
    let input = String::from("alpha beta gamma");
    let got = longest_word(&input);
    let start = input.as_ptr() as usize;
    let end = start + input.len();
    let ptr = got.as_ptr() as usize;
    assert!(
        ptr >= start && ptr < end,
        "returned slice does not point into the input buffer"
    );
}
