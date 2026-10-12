"""Tiny ledger analytics used by the nightly finance digest."""

HEADER = "day,amount"


def parse_log(text):
    """Parse 'day,amount' lines into sorted (day, amount) tuples."""
    rows = []
    for line in text.strip().splitlines():
        if line.strip() == HEADER:
            continue
        day, amount = line.split(",")
        rows.append((int(day), int(amount)))
    rows.sort()
    return rows


def cumulative(rows):
    """Running total of amounts in row order."""
    out = []
    total = 0
    for _, amount in rows:
        total += amount
        out.append(total)
    return out


def window_sums(rows, width):
    """Sum of each trailing window of `width` days (short at the start)."""
    amounts = [amount for _, amount in rows]
    out = []
    for i in range(len(amounts)):
        start = max(0, i - width + 1)
        out.append(sum(amounts[start:i + 1]))
    return out


def daily_report(text, width):
    rows = parse_log(text)
    return {
        "days": [day for day, _ in rows],
        "totals": cumulative(rows),
        "windows": window_sums(rows, width),
    }
