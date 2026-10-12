"""Shift report aggregation.

``shift_report(events)`` takes a list of event records; each record is a dict
with a "shift" name and a non-negative "units" count. It returns a list of
(shift, total_units) tuples, one per distinct shift, ordered by total units
descending. Shifts with equal totals must appear in the order in which they
first occur in the event list.
"""


def shift_report(events):
    totals = {}
    for event in events:
        shift = event["shift"]
        totals[shift] = totals.get(shift, 0) + event["units"]
    return sorted(totals.items(), key=lambda item: -item[1])
