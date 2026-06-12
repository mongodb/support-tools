"""Tests for Copy in natural order card."""

import unittest

from lib.live_metadata_status import parse_copy_in_natural_order_filter
from lib.live_monitoring import _build_display, _build_natural_order


class TestParseCopyInNaturalOrderFilter(unittest.TestCase):
    def test_select_all(self):
        rows = parse_copy_in_natural_order_filter({"selectAll": True, "dbsAndColls": {}})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["database"], "All")
        self.assertEqual(rows[0]["collections"], "All databases and collections")

    def test_dbs_and_colls(self):
        rows = parse_copy_in_natural_order_filter(
            {
                "selectAll": False,
                "dbsAndColls": {
                    "mydb": ["coll1", "coll2"],
                    "otherdb": [],
                },
            }
        )
        self.assertEqual(len(rows), 2)
        by_db = {r["database"]: r["collections"] for r in rows}
        self.assertEqual(by_db["mydb"], "coll1, coll2")
        self.assertEqual(by_db["otherdb"], "All collections")

    def test_empty_returns_none(self):
        self.assertIsNone(parse_copy_in_natural_order_filter(None))
        self.assertIsNone(parse_copy_in_natural_order_filter({}))
        self.assertIsNone(
            parse_copy_in_natural_order_filter({"selectAll": False, "dbsAndColls": {}})
        )


class TestNaturalOrderDisplay(unittest.TestCase):
    def test_build_natural_order_from_metadata(self):
        metadata = {
            "naturalOrderRows": [
                {"database": "mydb", "collections": "coll1, coll2"},
            ]
        }
        card = _build_natural_order(metadata)
        self.assertEqual(card["title"], "Copy in natural order")
        self.assertIn("natural insertion order", card["description"])
        self.assertEqual(card["label"], "Natural order collections")
        self.assertEqual(len(card["rows"]), 1)

    def test_build_natural_order_empty(self):
        self.assertIsNone(_build_natural_order({"naturalOrderRows": None}))
        self.assertIsNone(_build_natural_order(None))

    def test_display_includes_natural_order_with_metadata(self):
        metadata = {
            "state": "RUNNING",
            "phase": "Collection copy",
            "naturalOrderRows": [
                {"database": "db1", "collections": "c1"},
            ],
        }
        display = _build_display(None, metadata, progress_available=False)
        self.assertIsNotNone(display["naturalOrder"])
        self.assertEqual(display["naturalOrder"]["rows"][0]["database"], "db1")

    def test_display_omits_natural_order_without_metadata(self):
        display = _build_display({"state": "RUNNING"}, None, progress_available=True)
        self.assertIsNone(display["naturalOrder"])

    def test_display_omits_natural_order_when_filter_empty(self):
        metadata = {"state": "RUNNING", "naturalOrderRows": None}
        display = _build_display(None, metadata, progress_available=False)
        self.assertIsNone(display["naturalOrder"])


if __name__ == "__main__":
    unittest.main()
