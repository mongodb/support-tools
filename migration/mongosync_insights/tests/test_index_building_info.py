"""Tests for Index building info card from globalState.buildIndexes."""

import unittest

from lib.live_metadata_status import describe_build_indexes_policy, format_build_indexes
from lib.live_monitoring import _build_display, _build_index_building_info


class TestDescribeBuildIndexesPolicy(unittest.TestCase):
    def test_all_known_policies(self):
        self.assertIn(
            "after the collection copy",
            describe_build_indexes_policy("afterDataCopy"),
        )
        self.assertIn(
            "during initialization",
            describe_build_indexes_policy("beforeDataCopy"),
        )
        self.assertIn(
            "Hashed indexes were skipped",
            describe_build_indexes_policy("excludeHashed"),
        )
        self.assertIn(
            "Hashed indexes will be skipped",
            describe_build_indexes_policy("excludeHashedAfterCopy"),
        )

    def test_never_returns_none(self):
        self.assertIsNone(describe_build_indexes_policy("never"))

    def test_unknown_or_missing_returns_none(self):
        self.assertIsNone(describe_build_indexes_policy(None))
        self.assertIsNone(describe_build_indexes_policy(""))
        self.assertIsNone(describe_build_indexes_policy("unknownValue"))


class TestFormatBuildIndexes(unittest.TestCase):
    def test_exclude_hashed_labels(self):
        self.assertEqual(
            format_build_indexes("excludeHashed"),
            "Exclude Hashed (Before Copy)",
        )
        self.assertEqual(
            format_build_indexes("excludeHashedAfterCopy"),
            "Exclude Hashed (After Copy)",
        )


class TestIndexBuildingInfoCard(unittest.TestCase):
    def test_build_index_building_info_from_metadata(self):
        metadata = {"buildIndexesRaw": "afterDataCopy"}
        card = _build_index_building_info(metadata)
        self.assertEqual(card["mode"], "info")
        self.assertEqual(card["title"], "Index building")
        self.assertIn("after the collection copy", card["description"])

    def test_build_index_building_info_unknown_policy(self):
        self.assertIsNone(_build_index_building_info({"buildIndexesRaw": "bogus"}))

    def test_display_metadata_only_shows_info_card_without_index_totals(self):
        metadata = {
            "state": "RUNNING",
            "phase": "Collection copy",
            "buildIndexesRaw": "afterDataCopy",
        }
        display = _build_display(None, metadata, progress_available=False)
        self.assertEqual(display["indexBuilding"]["mode"], "info")
        self.assertIn("after the collection copy", display["indexBuilding"]["description"])

    def test_display_never_shows_no_info_card(self):
        metadata = {"state": "RUNNING", "phase": "Collection copy", "buildIndexesRaw": "never"}
        display = _build_display(None, metadata, progress_available=False)
        self.assertIsNone(display["indexBuilding"])

    def test_display_live_progress_takes_precedence(self):
        progress = {
            "state": "RUNNING",
            "indexBuilding": {
                "indexesBuilt": 5,
                "totalIndexesToBuild": 10,
                "collectionsFinished": 1,
                "collectionsTotal": 2,
            },
        }
        metadata = {"buildIndexesRaw": "never"}
        display = _build_display(progress, metadata, progress_available=True)
        self.assertNotIn("mode", display["indexBuilding"])
        self.assertEqual(display["indexBuilding"]["built"], 5)

    def test_display_no_metadata_no_index_card_without_progress_data(self):
        progress = {"state": "RUNNING"}
        display = _build_display(progress, None, progress_available=True)
        self.assertIsNone(display["indexBuilding"])


if __name__ == "__main__":
    unittest.main()
