"""nested_flatten.py

Recursively flatten arbitrarily nested lists and tuples into a single
flat list, preserving element order. Strings (and bytes) are treated as
atomic elements and are never split into individual characters.

Exported API:
    flatten -- flatten a nested structure into a flat list
"""

__all__ = ["flatten"]


def flatten(nested):
    """Recursively flatten *nested* lists and tuples into a flat list.

    Any element that is not a list or a tuple (including strings,
    bytes, numbers, dicts, sets, generators, and None) is treated as
    an atomic value and appears in the result unchanged.

    Args:
        nested: An arbitrarily nested structure of lists and tuples,
            or any single atomic value.

    Returns:
        list: A new flat list containing the atomic elements of
        *nested* in their original order.

    Examples:
        >>> flatten([1, (2, [3, "abc"]), [[4], []]])
        [1, 2, 3, 'abc', 4]
        >>> flatten("hello")
        ['hello']
        >>> flatten([])
        []
        >>> flatten((((5,),),))
        [5]
    """
    if not isinstance(nested, (list, tuple)):
        return [nested]

    flat = []
    for item in nested:
        flat.extend(flatten(item))
    return flat


if __name__ == "__main__":
    import doctest

    doctest.testmod(verbose=False)
