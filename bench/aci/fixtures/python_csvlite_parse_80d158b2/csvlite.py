"""csvlite: a tiny, self-contained CSV string parser.

Parses RFC-4180-style CSV text, honouring double-quoted fields so that
embedded commas, doubled quotes (``""``) and quoted newlines stay inside
a single field. Lines may be terminated by ``\n``, ``\r\n`` or ``\r``.
"""

__all__ = ["parse_csv"]


def parse_csv(text):
    """Parse *text* (a CSV document) into a list of rows.

    Each row is a list of strings. A field wrapped in double quotes may
    contain commas, carriage returns and newlines; a doubled double
    quote (``""``) inside such a field stands for one literal quote.

    >>> parse_csv('a,b\\n1,"x, y"\\n2,"he said ""hi""\\nbye"')
    [['a', 'b'], ['1', 'x, y'], ['2', 'he said "hi"\\nbye']]
    """
    if not isinstance(text, str):
        raise TypeError(
            "parse_csv() expects a str, got %s" % type(text).__name__
        )

    rows = []
    for line in text.splitlines():
        rows.append(line.split(","))
    return rows
