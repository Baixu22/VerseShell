"""Failing tests for salesagg: ties in per-region max must keep the FIRST
seller seen in input order, not the alphabetically smallest name."""

import os
import tempfile
import unittest

import salesagg


class MaxSaleByRegionTieTests(unittest.TestCase):
    def test_simple_tie_keeps_first_seen_seller(self):
        records = [
            ("east", "zeta", 100.0),
            ("east", "alpha", 100.0),
        ]
        result = salesagg.max_sale_by_region(records)
        self.assertIn("east", result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result["east"][0], "zeta")
        self.assertEqual(result["east"][1], 100.0)
        self.assertNotEqual(result["east"][0], "alpha")

    def test_tie_with_later_higher_sale_still_wins(self):
        records = [
            ("east", "zeta", 100.0),
            ("east", "alpha", 100.0),
            ("east", "mike", 250.0),
        ]
        result = salesagg.max_sale_by_region(records)
        self.assertEqual(result["east"][0], "mike")
        self.assertEqual(result["east"][1], 250.0)

    def test_multiple_regions_tie_keeps_first_seen(self):
        records = [
            ("west", "brooke", 50.0),
            ("west", "aaron", 50.0),
            ("north", "mel", 75.0),
            ("north", "abe", 75.0),
            ("north", "zed", 75.0),
        ]
        result = salesagg.max_sale_by_region(records)
        self.assertEqual(len(result), 2)
        self.assertEqual(result["west"][0], "brooke")
        self.assertEqual(result["west"][1], 50.0)
        self.assertEqual(result["north"][0], "mel")
        self.assertEqual(result["north"][1], 75.0)
        self.assertNotEqual(result["west"][0], "aaron")
        self.assertNotEqual(result["north"][0], "abe")

    def test_tie_interleaved_across_regions(self):
        records = [
            ("east", "dora", 30.0),
            ("west", "carl", 20.0),
            ("east", "anna", 30.0),
            ("west", "brad", 20.0),
        ]
        result = salesagg.max_sale_by_region(records)
        self.assertEqual(result["east"][0], "dora")
        self.assertEqual(result["east"][1], 30.0)
        self.assertEqual(result["west"][0], "carl")
        self.assertEqual(result["west"][1], 20.0)

    def test_non_tie_picks_higher_amount_regardless_of_name(self):
        records = [
            ("south", "first", 10.0),
            ("south", "aaa", 20.0),
            ("south", "zzz", 5.0),
        ]
        result = salesagg.max_sale_by_region(records)
        self.assertEqual(result["south"][0], "aaa")
        self.assertEqual(result["south"][1], 20.0)

    def test_strictly_greater_later_beats_earlier_alphabetical(self):
        records = [
            ("east", "aaa", 10.0),
            ("east", "zzz", 20.0),
        ]
        result = salesagg.max_sale_by_region(records)
        self.assertEqual(result["east"][0], "zzz")
        self.assertEqual(result["east"][1], 20.0)

    def test_single_record_region(self):
        result = salesagg.max_sale_by_region([("east", "only", 1.0)])
        self.assertIn("east", result)
        self.assertEqual(result["east"][0], "only")
        self.assertEqual(result["east"][1], 1.0)

    def test_empty_records(self):
        self.assertEqual(salesagg.max_sale_by_region([]), {})


class TotalsByRegionTests(unittest.TestCase):
    def test_totals_sum_per_region(self):
        records = [
            ("east", "a", 10.0),
            ("east", "b", 5.0),
            ("west", "c", 2.5),
        ]
        totals = salesagg.totals_by_region(records)
        self.assertEqual(totals["east"], 15.0)
        self.assertEqual(totals["west"], 2.5)
        self.assertEqual(len(totals), 2)


class ReportTests(unittest.TestCase):
    def _write_csv(self, rows):
        fd, path = tempfile.mkstemp(suffix=".csv")
        self.addCleanup(os.remove, path)
        with os.fdopen(fd, "w", newline="") as f:
            f.write("region,seller,amount\n")
            for region, seller, amount in rows:
                f.write(f"{region},{seller},{amount}\n")
        return path

    def test_report_tie_uses_first_seen_seller(self):
        path = self._write_csv([
            ("east", "zulu", 120.0),
            ("east", "alpha", 120.0),
            ("east", "bravo", 40.0),
            ("west", "yara", 90.0),
            ("west", "adam", 90.0),
        ])
        result = salesagg.report(path)
        lines = result.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "east: top=zulu (120.00) total=280.00")
        self.assertEqual(lines[1], "west: top=yara (90.00) total=180.00")
        self.assertIn("top=zulu", result)
        self.assertIn("top=yara", result)
        self.assertNotIn("top=alpha", result)
        self.assertNotIn("top=adam", result)


if __name__ == "__main__":
    unittest.main()
