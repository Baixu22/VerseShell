import pytest

from batches import split_into_batches


def test_preserves_every_item():
    batches = split_into_batches(list(range(10)), 3)
    assert [x for batch in batches for x in batch] == list(range(10))


def test_balanced_sizes():
    batches = split_into_batches(list(range(10)), 3)
    assert [len(b) for b in batches] == [4, 3, 3]


def test_more_batches_than_items():
    assert split_into_batches(["a"], 4) == [["a"], [], [], []]


def test_exact_division():
    assert split_into_batches([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_single_batch_keeps_everything():
    assert split_into_batches([1, 2, 3], 1) == [[1, 2, 3]]


def test_rejects_non_positive_batch_count():
    with pytest.raises(ValueError):
        split_into_batches([1], 0)
