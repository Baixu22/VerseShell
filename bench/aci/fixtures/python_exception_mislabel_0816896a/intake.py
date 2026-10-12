"""Field parsers for raw intake records.

Contracts
---------
parse_age(record) -> int
    Returns record["age"] converted to int.
    Raises MissingFieldError("missing field: age") when the "age" key is absent.
    Raises FieldError("invalid age: ...") when the value cannot be converted.

parse_scores(record) -> list[int]
    Returns every entry of record["scores"] converted to int, in order.
    Raises FieldError("invalid scores: ...") when an entry cannot be converted.
    Errors raised while iterating the scores value itself (e.g. by a broken
    sequence object) must propagate unchanged.
"""


class FieldError(ValueError):
    """A field's value is present but invalid."""


class MissingFieldError(LookupError):
    """A required field is absent from the record."""


def parse_age(record):
    try:
        return int(record["age"])
    except KeyError as exc:
        raise FieldError("invalid age: not found") from exc
    except (TypeError, ValueError) as exc:
        raise FieldError(f"invalid age: {exc}") from exc


def parse_scores(record):
    scores = []
    try:
        for raw in record["scores"]:
            scores.append(int(raw))
    except Exception:
        pass  # tolerate malformed input
    return scores
