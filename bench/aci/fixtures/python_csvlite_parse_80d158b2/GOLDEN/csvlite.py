"""csvlite: a tiny, self-contained CSV string parser.

Parses RFC-4180-style CSV text, honouring double-quoted fields so that
embedded commas, doubled quotes (``""``) and quoted newlines stay inside
a single field. Lines may be terminated by ``\n``, ``\r\n`` or ``\r``.
"""

__all__ = ["parse_csv"]

# Parser states.
_START = 0        # at the very beginning of a field
_IN_FIELD = 1     # inside an unquoted field
_IN_QUOTED = 2    # inside a double-quoted field
_AFTER_QUOTE = 3  # just consumed the closing quote of a quoted field


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
    row = []
    field = []
    state = _START
    i = 0
    n = len(text)

    def flush_field():
        row.append("".join(field))
        del field[:]

    def flush_row():
        rows.append(row[:])
        del row[:]

    while i < n:
        ch = text[i]

        if state == _IN_QUOTED:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')   # doubled quote -> literal quote
                    i += 2
                    continue
                state = _AFTER_QUOTE    # closing quote
                i += 1
                continue
            field.append(ch)            # commas/newlines stay literal
            i += 1
            continue

        # Row terminator (outside quotes): \n, \r\n or \r.
        if ch == "\n" or ch == "\r":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1                  # swallow the \n of a CRLF pair
            if state == _START and not row:
                flush_row()             # completely blank line
            else:
                flush_field()
                flush_row()
            state = _START
            i += 1
            continue

        # Field separator (outside quotes).
        if ch == ",":
            flush_field()
            state = _START
            i += 1
            continue

        # An opening quote only counts at the start of a field.
        if ch == '"' and state == _START:
            state = _IN_QUOTED
            i += 1
            continue

        # Any other character (including stray quotes after a closing
        # quote or inside an unquoted field) is taken literally.
        field.append(ch)
        if state == _START:
            state = _IN_FIELD
        i += 1

    # End of input: emit any pending field/row. A trailing newline has
    # already flushed its row and leaves nothing pending.
    if state != _START or row or field:
        flush_field()
        flush_row()

    return rows
