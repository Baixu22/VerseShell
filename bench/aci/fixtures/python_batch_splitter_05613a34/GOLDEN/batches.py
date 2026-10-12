"""Split a list of items into ordered batches."""


def split_into_batches(items, batch_count):
    """Divide ``items`` (in order) into exactly ``batch_count`` batches.

    Every item must appear in exactly one batch, batches keep the original
    order, and batch sizes may differ by at most one.

    Raises:
        ValueError: if ``batch_count`` is less than 1.
    """
    if batch_count < 1:
        raise ValueError("batch_count must be at least 1")
    base, extra = divmod(len(items), batch_count)
    batches = []
    start = 0
    for index in range(batch_count):
        end = start + base + (1 if index < extra else 0)
        batches.append(list(items[start:end]))
        start = end
    return batches
