"""salesagg: aggregate sales records by region."""

import csv
from collections import defaultdict


def load_sales(path):
    records = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            records.append((row["region"], row["seller"], float(row["amount"])))
    return records


def max_sale_by_region(records):
    """Top sale per region; ties broken alphabetically by seller name."""
    best = {}
    for region, seller, amount in records:
        if region not in best or amount > best[region][1]:
            best[region] = (seller, amount)
        elif amount == best[region][1] and seller < best[region][0]:
            best[region] = (seller, amount)
    return best


def totals_by_region(records):
    totals = defaultdict(float)
    for region, _, amount in records:
        totals[region] += amount
    return dict(totals)


def report(path):
    records = load_sales(path)
    top = max_sale_by_region(records)
    totals = totals_by_region(records)
    return "\n".join(
        f"{r}: top={top[r][0]} ({top[r][1]:.2f}) total={totals[r]:.2f}"
        for r in sorted(top)
    )


if __name__ == "__main__":
    import sys
    print(report(sys.argv[1]))
