"""Utilities for parsing simple comma-separated order lines.

Each data line has the form ``name,qty`` where ``qty`` is an integer.
"""


def parse_orders(text: str) -> list[tuple[str, int]]:
    """Parse ``text`` and return one (name, qty) tuple per data line.

    Blank lines are not data lines. A row without a quantity field
    counts as an order with quantity 0.
    """
    orders = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(",")
        name = parts[0]
        qty = 0
        if len(parts) > 1 and parts[1].strip():
            qty = int(parts[1])
        orders.append((name, qty))
    return orders


def total_quantity(text: str) -> int:
    """Return the sum of the quantities of all orders in ``text``."""
    return sum(qty for _, qty in parse_orders(text))
