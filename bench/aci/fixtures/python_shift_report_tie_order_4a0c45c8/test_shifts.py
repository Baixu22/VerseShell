from shifts import shift_report


def test_totals_sorted_descending_without_ties():
    events = [
        {"shift": "day", "units": 10},
        {"shift": "night", "units": 4},
        {"shift": "night", "units": 5},
        {"shift": "day", "units": 2},
    ]
    assert shift_report(events) == [("day", 12), ("night", 9)]


def test_equal_totals_keep_first_seen_order():
    events = [
        {"shift": "swing", "units": 7},
        {"shift": "day", "units": 9},
        {"shift": "graveyard", "units": 7},
        {"shift": "day", "units": 4},
    ]
    assert shift_report(events) == [("day", 13), ("swing", 7), ("graveyard", 7)]


def test_three_way_tie_keeps_first_seen_order():
    events = [
        {"shift": "mid", "units": 1},
        {"shift": "low", "units": 1},
        {"shift": "high", "units": 1},
    ]
    assert shift_report(events) == [("mid", 1), ("low", 1), ("high", 1)]


def test_empty_input():
    assert shift_report([]) == []


def test_single_event():
    assert shift_report([{"shift": "night", "units": 3}]) == [("night", 3)]
