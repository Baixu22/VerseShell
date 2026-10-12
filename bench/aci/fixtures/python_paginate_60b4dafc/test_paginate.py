"""Failing tests for the paginate module's page-slicing behavior.

The bug under test: ``paginate`` computes the slice end as
``start + size - 1`` while treating it as an exclusive slice bound,
so every full page silently drops its final item.
"""

import unittest

from paginate import all_pages, page_count, paginate


class TestPaginateSinglePage(unittest.TestCase):
    def test_full_page_keeps_every_item(self):
        items = list(range(1, 11))  # 10 items
        result = paginate(items, page=1, size=10)
        self.assertEqual(len(result), 10)
        self.assertEqual(result, items)
        self.assertEqual(result[0], 1)
        self.assertEqual(result[1], 2)
        self.assertEqual(result[4], 5)
        self.assertEqual(result[8], 9)
        self.assertEqual(result[-1], 10)

    def test_page_size_smaller_than_items(self):
        items = ["a", "b", "c", "d", "e", "f"]
        page1 = paginate(items, page=1, size=3)
        self.assertEqual(len(page1), 3)
        self.assertEqual(page1, ["a", "b", "c"])
        self.assertEqual(page1[0], "a")
        self.assertEqual(page1[1], "b")
        self.assertEqual(page1[-1], "c")

    def test_second_page_boundaries(self):
        items = list(range(1, 10))  # 1..9
        page2 = paginate(items, page=2, size=3)
        self.assertEqual(len(page2), 3)
        self.assertEqual(page2, [4, 5, 6])
        self.assertEqual(page2[0], 4)
        self.assertEqual(page2[1], 5)
        self.assertEqual(page2[-1], 6)

    def test_third_page_boundaries(self):
        items = list(range(1, 10))  # 1..9
        page3 = paginate(items, page=3, size=3)
        self.assertEqual(len(page3), 3)
        self.assertEqual(page3, [7, 8, 9])
        self.assertEqual(page3[0], 7)
        self.assertEqual(page3[-1], 9)

    def test_partial_last_page(self):
        items = list(range(1, 11))  # 10 items
        page4 = paginate(items, page=4, size=3)
        self.assertEqual(len(page4), 1)
        self.assertEqual(page4, [10])

    def test_page_beyond_content_is_empty(self):
        items = [1, 2, 3]
        self.assertEqual(paginate(items, page=2, size=3), [])
        self.assertEqual(paginate(items, page=99, size=3), [])

    def test_default_arguments(self):
        items = list(range(20))
        result = paginate(items)
        self.assertEqual(len(result), 10)
        self.assertEqual(result[0], 0)
        self.assertEqual(result[9], 9)


class TestAllPages(unittest.TestCase):
    def test_no_items_lost_across_pages(self):
        items = list(range(1, 10))  # exactly 3 full pages of size 3
        pages = all_pages(items, size=3)
        self.assertEqual(len(pages), 3)
        self.assertEqual(len(pages[0]), 3)
        self.assertEqual(len(pages[1]), 3)
        self.assertEqual(len(pages[2]), 3)
        flattened = [item for page in pages for item in page]
        self.assertEqual(flattened, items)
        self.assertEqual(len(flattened), 9)

    def test_each_page_matches_single_page_calls(self):
        items = list(range(12))
        pages = all_pages(items, size=4)
        self.assertEqual(pages[0], paginate(items, page=1, size=4))
        self.assertEqual(pages[1], paginate(items, page=2, size=4))
        self.assertEqual(pages[2], paginate(items, page=3, size=4))
        self.assertEqual(pages[0], [0, 1, 2, 3])
        self.assertEqual(pages[1], [4, 5, 6, 7])
        self.assertEqual(pages[2], [8, 9, 10, 11])

    def test_empty_input(self):
        self.assertEqual(all_pages([], size=5), [])
        self.assertEqual(page_count([], size=5), 0)

    def test_page_count_is_consistent_with_pages_produced(self):
        items = list(range(7))
        count = page_count(items, size=3)
        pages = all_pages(items, size=3)
        self.assertEqual(count, 3)
        self.assertEqual(len(pages), count)
        flattened = [item for page in pages for item in page]
        self.assertEqual(flattened, items)
        self.assertEqual(len(flattened), 7)


class TestValidation(unittest.TestCase):
    def test_invalid_size(self):
        with self.assertRaises(ValueError):
            paginate([1, 2, 3], page=1, size=0)
        with self.assertRaises(ValueError):
            paginate([1, 2, 3], page=1, size=-2)

    def test_invalid_page(self):
        with self.assertRaises(ValueError):
            paginate([1, 2, 3], page=0, size=2)
        with self.assertRaises(ValueError):
            paginate([1, 2, 3], page=-1, size=2)

    def test_page_count_invalid_size(self):
        with self.assertRaises(ValueError):
            page_count([1, 2, 3], size=0)


if __name__ == "__main__":
    unittest.main()
