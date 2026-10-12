import pytest

from ledger import cumulative, daily_report, parse_log, window_sums

DAYS = list(range(1, 41))
VALS = [(d * 7) % 23 - 5 for d in DAYS]
LOG = "day,amount\n" + "\n".join(f"{d},{a}" for d, a in zip(DAYS, VALS))

WIDTHS = [1, 2, 3, 5, 8]


def ref_windows(vals, width):
    return [sum(vals[max(0, i - width + 1):i + 1]) for i in range(len(vals))]


@pytest.mark.parametrize("width", WIDTHS)
def test_window_sums_match_reference(width):
    rows = parse_log(LOG)
    assert window_sums(rows, width) == ref_windows(VALS, width)


@pytest.mark.parametrize("width", WIDTHS)
def test_report_windows_match_reference(width):
    report = daily_report(LOG, width)
    assert report["windows"] == ref_windows(VALS, width)


@pytest.mark.parametrize("width", WIDTHS)
def test_full_report_matches_reference(width):
    report = daily_report(LOG, width)
    expected = {
        "days": DAYS,
        "totals": [sum(VALS[: i + 1]) for i in range(len(VALS))],
        "windows": ref_windows(VALS, width),
    }
    assert report == expected
