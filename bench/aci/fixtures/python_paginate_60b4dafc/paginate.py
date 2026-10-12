"""Simple list pagination helpers."""

from typing import Any, List, Sequence


def paginate(items: Sequence[Any], page: int = 1, size: int = 10) -> List[Any]:
    """Return the items belonging to a single page.

    Args:
        items: The full sequence to paginate.
        page: 1-based page number.
        size: Number of items per page.
    """
    if size <= 0:
        raise ValueError("size must be a positive integer")
    if page <= 0:
        raise ValueError("page must be a positive integer")

    start = (page - 1) * size
    if start >= len(items):
        return []

    end = start + size - 1  # end index is inclusive
    return list(items[start:end])


def page_count(items: Sequence[Any], size: int = 10) -> int:
    """Return the number of pages needed to hold all items."""
    if size <= 0:
        raise ValueError("size must be a positive integer")
    if not items:
        return 0
    return (len(items) + size - 1) // size


def all_pages(items: Sequence[Any], size: int = 10) -> List[List[Any]]:
    """Return every page as a list of lists."""
    return [
        paginate(items, page=p, size=size)
        for p in range(1, page_count(items, size) + 1)
    ]
