import pytest

from intake import FieldError, MissingFieldError, parse_age, parse_scores


class ProbeError(RuntimeError):
    pass


class BoomSeq:
    def __iter__(self):
        raise ProbeError("iteration exploded")


def test_age_happy():
    assert parse_age({"age": "42"}) == 42


def test_age_missing_raises_missing_field():
    with pytest.raises(MissingFieldError) as excinfo:
        parse_age({"name": "ann"})
    assert "missing field: age" in str(excinfo.value)


def test_age_invalid_value_raises_field_error():
    with pytest.raises(FieldError) as excinfo:
        parse_age({"age": "soon"})
    assert "invalid age" in str(excinfo.value)


def test_scores_happy():
    assert parse_scores({"scores": [3, "4", 5]}) == [3, 4, 5]


def test_scores_bad_entry_raises_field_error():
    with pytest.raises(FieldError):
        parse_scores({"scores": [1, "x"]})


def test_scores_iteration_error_propagates():
    with pytest.raises(ProbeError):
        parse_scores({"scores": BoomSeq()})
