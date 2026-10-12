from orders import parse_orders, total_quantity


def test_basic_rows():
    assert parse_orders("apple,3\nbanana,2") == [("apple", 3), ("banana", 2)]


def test_blank_lines_are_skipped():
    text = "\napple,3\n\n   \nbanana,2\n\n"
    assert parse_orders(text) == [("apple", 3), ("banana", 2)]


def test_missing_quantity_column_is_zero():
    assert parse_orders("apple,3\ncherry\nbanana,2") == [
        ("apple", 3),
        ("cherry", 0),
        ("banana", 2),
    ]


def test_trailing_comma_means_missing_qty():
    assert parse_orders("apple,\nbanana,2") == [("apple", 0), ("banana", 2)]


def test_total_quantity_ignores_blank_and_missing():
    text = "apple,3\n\nbanana,2\ncherry\n"
    assert total_quantity(text) == 5
