"""Tests for nested_flatten.flatten.

Every test calls the exported ``flatten`` function with a distinct,
independently constructed nested structure and compares the result
against a long literal, so any regression produces a long failure diff.
"""

from nested_flatten import flatten


def test_deeply_nested_numbers():
    nested = [1, [2, (3, [4, (5, [6]), 7]), 8], (9, [10, (11, 12)]), 13]
    assert flatten(nested) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]


def test_strings_never_split():
    nested = [
        "alpha",
        ["beta", ("gamma", ["delta", "epsilon"])],
        "zeta",
        ["eta", "theta", ("iota", ["kappa"])],
    ]
    assert flatten(nested) == [
        "alpha", "beta", "gamma", "delta", "epsilon",
        "zeta", "eta", "theta", "iota", "kappa",
    ]


def test_empty_containers_vanish():
    nested = [
        [], (1, []), [[], [2, []]], (), ((3, ()), []), 4,
        ([], [5, 6]), 7, ((8,), [], (9,)), 10,
    ]
    assert flatten(nested) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_bytes_treated_atomically():
    nested = [
        b"one",
        [b"two", (b"three", [b"four"])],
        b"five",
        (b"six", [b"seven", b"eight"]),
        [b"nine", b"ten"],
    ]
    assert flatten(nested) == [
        b"one", b"two", b"three", b"four", b"five",
        b"six", b"seven", b"eight", b"nine", b"ten",
    ]


def test_mixed_scalar_types():
    nested = [
        1,
        ["two", (3.5, ["four"])],
        None,
        (True, [5]),
        "six",
        [7.25, (None, ["eight"]), 9],
        [10],
    ]
    assert flatten(nested) == [
        1, "two", 3.5, "four", None, True, 5,
        "six", 7.25, None, "eight", 9, 10,
    ]


def test_dicts_are_atomic():
    nested = [
        {"a": 1},
        [2, {"b": 3}, ({"c": 4}, [5, {"d": 6}])],
        {"e": 7},
        (8, [{"f": 9}, 10]),
        {"g": 11},
    ]
    assert flatten(nested) == [
        {"a": 1}, 2, {"b": 3}, {"c": 4}, 5, {"d": 6},
        {"e": 7}, 8, {"f": 9}, 10, {"g": 11},
    ]


def test_sets_and_frozensets_atomic():
    nested = [
        {1, 2},
        [{3, 4}, (frozenset({5, 6}), [{7}, 8])],
        frozenset({9, 10}),
        (11, [{12, 13}, ({14}, 15)]),
        [16, {17, 18}],
    ]
    assert flatten(nested) == [
        {1, 2}, {3, 4}, frozenset({5, 6}), {7}, 8,
        frozenset({9, 10}), 11, {12, 13}, {14}, 15, 16, {17, 18},
    ]


def test_ranges_treated_atomically():
    nested = [
        range(3),
        [range(4, 7), (range(7, 10), [1, 2])],
        range(10, 12),
        (3, 4),
        [[range(12, 15)], 5],
    ]
    assert flatten(nested) == [
        range(3), range(4, 7), range(7, 10), 1, 2,
        range(10, 12), 3, 4, range(12, 15), 5,
    ]


def test_tuple_only_nesting():
    nested = (1, (2, 3, (4, (5, (6, 7)), 8)), (9,), ((10, 11), 12), 13)
    assert flatten(nested) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]


def test_list_only_nesting():
    nested = [
        [[1, 2], [3]],
        [4, [[5], [6, [7]]]],
        [8],
        [9, [10, [11, [12]]]],
        13,
        [14],
    ]
    assert flatten(nested) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]


def test_atomic_single_values():
    assert flatten("abcdefghij") == ["abcdefghij"]
    assert flatten(12345) == [12345]
    assert flatten((((5,),),)) == [5]
    assert flatten([1, [2, [3, [4, [5, [6, [7, [8, [9, [10]]]]]]]]]]) == [
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
    ]


def test_numeric_variety():
    nested = [
        -1,
        [-2.5, (-3, [-4.75, (-5,), -6])],
        [-7, (-8.125, [-9])],
        -10,
    ]
    assert flatten(nested) == [-1, -2.5, -3, -4.75, -5, -6, -7, -8.125, -9, -10]


def test_unicode_strings_atomic():
    nested = [
        "héllo",
        ["wörld", ("日本語", ["тест", "🎉party"])],
        "naïve",
        ["résumé", ("café", ["über", "olé"])],
    ]
    assert flatten(nested) == [
        "héllo", "wörld", "日本語", "тест", "🎉party",
        "naïve", "résumé", "café", "über", "olé",
    ]


def test_none_values_preserved():
    nested = [
        None,
        [None, (1, [None, 2]), None],
        (3, [None]),
        [4, None, 5],
    ]
    assert flatten(nested) == [
        None, None, 1, None, 2, None, 3, None, 4, None, 5,
    ]


def test_left_deep_chain():
    nested = [[[[[[[[[1, 2], 3], 4], 5], 6], 7], 8], 9], 10]
    assert flatten(nested) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_right_deep_tuple_chain():
    nested = (1, 2, (3, 4, (5, 6, (7, 8, (9, 10, (11, 12))))))
    assert flatten(nested) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]


def test_booleans_preserved():
    nested = [
        True,
        [False, (True, [False, False])],
        True,
        [False, (True, [False])],
        [True, False, True],
    ]
    assert flatten(nested) == [
        True, False, True, False, False,
        True, False, True, False, True, False, True,
    ]


def test_digit_strings_whole():
    nested = [
        "12345",
        ["67890", ("11121", ["31415"])],
        "92653",
        ("58979", ["32384"]),
        "62643",
        ["38327", ("95028", ["84197"])],
    ]
    assert flatten(nested) == [
        "12345", "67890", "11121", "31415", "92653", "58979",
        "32384", "62643", "38327", "95028", "84197",
    ]
