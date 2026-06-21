"""Tests for Filtered migration card."""

import unittest

from lib.live_metadata_status import (
    format_namespace_filter_rows,
    namespace_filter_is_active,
)
from lib.live_monitoring import _build_display, _build_filtered_migration


class TestFormatNamespaceFilterRows(unittest.TestCase):
    def test_empty_inclusion_defaults(self):
        rows = format_namespace_filter_rows(None, "inclusion")
        self.assertEqual(rows, [{"key": "Database", "value": "All (no filter)"}])

    def test_empty_exclusion_defaults(self):
        rows = format_namespace_filter_rows(None, "exclusion")
        self.assertEqual(rows, [{"key": "Filter", "value": "No filter"}])

    def test_inclusion_with_database_and_collections(self):
        rows = format_namespace_filter_rows(
            [{"database": ["mydb"], "collections": ["c1", "c2"]}],
            "inclusion",
        )
        by_key = {r["key"]: r["value"] for r in rows}
        self.assertEqual(by_key["Database"], "mydb")
        self.assertEqual(by_key["Collections"], "c1, c2")

    def test_exclusion_with_entries(self):
        rows = format_namespace_filter_rows(
            [{"database": ["otherdb"], "collections": ["x"]}],
            "exclusion",
        )
        self.assertTrue(any(r["key"] == "Database" for r in rows))
        self.assertTrue(any(r["key"] == "Collections" for r in rows))


class TestNamespaceFilterIsActive(unittest.TestCase):
    def test_active_when_inclusion_set(self):
        self.assertTrue(
            namespace_filter_is_active(
                {"inclusionFilter": [{"database": ["db1"]}], "exclusionFilter": None}
            )
        )

    def test_active_when_exclusion_set(self):
        self.assertTrue(
            namespace_filter_is_active(
                {"inclusionFilter": None, "exclusionFilter": [{"database": ["db1"]}]}
            )
        )

    def test_inactive_when_empty(self):
        self.assertFalse(namespace_filter_is_active(None))
        self.assertFalse(namespace_filter_is_active({}))
        self.assertFalse(
            namespace_filter_is_active({"inclusionFilter": [], "exclusionFilter": []})
        )


class TestFilteredMigrationDisplay(unittest.TestCase):
    def test_build_filtered_migration_from_metadata(self):
        metadata = {
            "namespaceFilterActive": True,
            "inclusionFilterRows": [{"key": "Database", "value": "mydb"}],
            "exclusionFilterRows": [{"key": "Filter", "value": "No filter"}],
        }
        card = _build_filtered_migration(metadata)
        self.assertEqual(card["title"], "Filtered migration")
        self.assertEqual(card["inclusion"]["label"], "Include")
        self.assertEqual(card["exclusion"]["label"], "Exclude")

    def test_build_filtered_migration_inactive(self):
        self.assertIsNone(_build_filtered_migration({"namespaceFilterActive": False}))
        self.assertIsNone(_build_filtered_migration(None))

    def test_display_includes_filtered_migration(self):
        metadata = {
            "state": "RUNNING",
            "phase": "Collection copy",
            "namespaceFilterActive": True,
            "inclusionFilterRows": [{"key": "Database", "value": "mydb"}],
            "exclusionFilterRows": [{"key": "Filter", "value": "No filter"}],
        }
        display = _build_display(None, metadata, progress_available=False)
        self.assertIsNotNone(display["filteredMigration"])
        self.assertEqual(display["filteredMigration"]["title"], "Filtered migration")

    def test_display_omits_filtered_migration_without_metadata(self):
        display = _build_display({"state": "RUNNING"}, None, progress_available=True)
        self.assertIsNone(display["filteredMigration"])

    def test_display_omits_filtered_migration_when_inactive(self):
        metadata = {
            "state": "RUNNING",
            "namespaceFilterActive": False,
            "inclusionFilterRows": [{"key": "Database", "value": "All (no filter)"}],
            "exclusionFilterRows": [{"key": "Filter", "value": "No filter"}],
        }
        display = _build_display(None, metadata, progress_available=False)
        self.assertIsNone(display["filteredMigration"])


if __name__ == "__main__":
    unittest.main()
