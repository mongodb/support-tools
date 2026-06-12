"""Tests for Index building totals and progress from indexCorrection metadata."""

import unittest
from unittest.mock import MagicMock, patch

from lib.index_build_destination_cache import clear_all
from lib.live_metadata_status import (
    _rollup_index_correction_groups,
    fetch_index_correction_status,
    index_build_progress_allowed,
    is_during_or_after_cea,
    should_suppress_index_build_progress,
)
from lib.live_monitoring import (
    _build_display,
    _build_index_building_from_metadata,
    build_live_monitor_payload,
)


class TestRollupIndexCorrectionGroups(unittest.TestCase):
    def test_all_indexes_pending(self):
        groups = [{"_id": "uuid-a", "indexesTotal": 3, "indexesPending": 3}]
        self.assertEqual(
            _rollup_index_correction_groups(groups),
            {
                "collectionsTotal": 1,
                "indexesTotal": 3,
                "indexesBuilt": 0,
                "collectionsFinished": 0,
            },
        )

    def test_all_indexes_built(self):
        groups = [
            {"_id": "uuid-a", "indexesTotal": 2, "indexesPending": 0},
            {"_id": "uuid-b", "indexesTotal": 1, "indexesPending": 0},
        ]
        self.assertEqual(
            _rollup_index_correction_groups(groups),
            {
                "collectionsTotal": 2,
                "indexesTotal": 3,
                "indexesBuilt": 3,
                "collectionsFinished": 2,
            },
        )

    def test_mixed_collections(self):
        groups = [
            {"_id": "uuid-a", "indexesTotal": 2, "indexesPending": 0},
            {"_id": "uuid-b", "indexesTotal": 2, "indexesPending": 2},
        ]
        self.assertEqual(
            _rollup_index_correction_groups(groups),
            {
                "collectionsTotal": 2,
                "indexesTotal": 4,
                "indexesBuilt": 2,
                "collectionsFinished": 1,
            },
        )

    def test_empty_groups_returns_none(self):
        self.assertIsNone(_rollup_index_correction_groups([]))

    def test_zero_indexes_total_returns_none(self):
        self.assertIsNone(
            _rollup_index_correction_groups(
                [{"_id": "uuid-a", "indexesTotal": 0, "indexesPending": 0}]
            )
        )


class TestFetchIndexCorrectionStatus(unittest.TestCase):
    def setUp(self):
        clear_all()

    def _setup_internal_db(self, groups, *, pending_docs=None, uuid_maps=None):
        internal_db = MagicMock()
        internal_db.indexCorrection.aggregate.return_value = groups
        internal_db.indexCorrection.find.return_value = pending_docs or []
        internal_db.uuidMap.find.return_value = uuid_maps or []
        return internal_db

    def test_returns_progress_from_counter_aggregate(self):
        internal_db = self._setup_internal_db(
            [
                {"_id": "uuid-a", "indexesTotal": 3, "indexesPending": 1},
            ]
        )

        result = fetch_index_correction_status(internal_db)

        self.assertEqual(
            result,
            {
                "collectionsTotal": 1,
                "indexesTotal": 3,
                "indexesBuilt": 2,
                "collectionsFinished": 0,
            },
        )
        internal_db.indexCorrection.aggregate.assert_called_once()

    def test_empty_aggregate_returns_none(self):
        internal_db = self._setup_internal_db([])
        self.assertIsNone(fetch_index_correction_status(internal_db))

    def test_two_collections_one_finished(self):
        internal_db = self._setup_internal_db(
            [
                {"_id": "uuid-a", "indexesTotal": 2, "indexesPending": 0},
                {"_id": "uuid-b", "indexesTotal": 1, "indexesPending": 1},
            ]
        )

        result = fetch_index_correction_status(internal_db)

        self.assertEqual(result["indexesBuilt"], 2)
        self.assertEqual(result["collectionsFinished"], 1)

    @patch("lib.live_metadata_status._fetch_destination_index_names")
    def test_counts_destination_verified_indexes_when_counters_lag(
        self, mock_fetch_dest_indexes
    ):
        coll_uuid = b"\x01" * 16
        internal_db = self._setup_internal_db(
            [{"_id": coll_uuid, "indexesTotal": 2, "indexesPending": 2}],
            pending_docs=[
                {
                    "_id": {
                        "dbName": "bar2",
                        "collUUID": coll_uuid,
                        "indexName": "idx_a",
                    }
                },
                {
                    "_id": {
                        "dbName": "bar2",
                        "collUUID": coll_uuid,
                        "indexName": "idx_b",
                    }
                },
            ],
            uuid_maps=[
                {
                    "_id": coll_uuid,
                    "dbName": "bar2",
                    "dstCollName": "coll1",
                }
            ],
        )
        mock_fetch_dest_indexes.return_value = {"_id_", "idx_a"}

        result = fetch_index_correction_status(internal_db, "mongodb://localhost")

        self.assertEqual(result["indexesBuilt"], 1)
        self.assertEqual(result["collectionsFinished"], 0)
        mock_fetch_dest_indexes.assert_called_once_with(
            "mongodb://localhost", "bar2", "coll1"
        )

    @patch("lib.live_metadata_status._fetch_destination_index_names")
    def test_missing_uuid_map_skips_destination_verification(
        self, mock_fetch_dest_indexes
    ):
        coll_uuid = b"\x02" * 16
        internal_db = self._setup_internal_db(
            [{"_id": coll_uuid, "indexesTotal": 1, "indexesPending": 1}],
            pending_docs=[
                {
                    "_id": {
                        "dbName": "foo",
                        "collUUID": coll_uuid,
                        "indexName": "idx_a",
                    }
                }
            ],
            uuid_maps=[],
        )

        result = fetch_index_correction_status(internal_db, "mongodb://localhost")

        self.assertEqual(result["indexesBuilt"], 0)
        mock_fetch_dest_indexes.assert_not_called()

    @patch("lib.live_metadata_status._fetch_destination_index_names")
    def test_list_indexes_failure_keeps_counter_only_progress(
        self, mock_fetch_dest_indexes
    ):
        coll_uuid = b"\x03" * 16
        internal_db = self._setup_internal_db(
            [{"_id": coll_uuid, "indexesTotal": 1, "indexesPending": 1}],
            pending_docs=[
                {
                    "_id": {
                        "dbName": "foo",
                        "collUUID": coll_uuid,
                        "indexName": "idx_a",
                    }
                }
            ],
            uuid_maps=[
                {
                    "_id": coll_uuid,
                    "dbName": "foo",
                    "dstCollName": "coll1",
                }
            ],
        )
        mock_fetch_dest_indexes.return_value = None

        result = fetch_index_correction_status(internal_db, "mongodb://localhost")

        self.assertEqual(result["indexesBuilt"], 0)

    @patch("lib.live_metadata_status._fetch_destination_index_names")
    def test_throttle_reuses_cached_destination_scan(self, mock_fetch_dest_indexes):
        coll_uuid = b"\x04" * 16
        internal_db = self._setup_internal_db(
            [{"_id": coll_uuid, "indexesTotal": 1, "indexesPending": 1}],
            pending_docs=[
                {
                    "_id": {
                        "dbName": "foo",
                        "collUUID": coll_uuid,
                        "indexName": "idx_a",
                    }
                }
            ],
            uuid_maps=[
                {
                    "_id": coll_uuid,
                    "dbName": "foo",
                    "dstCollName": "coll1",
                }
            ],
        )
        mock_fetch_dest_indexes.return_value = {"_id_", "idx_a"}

        fetch_index_correction_status(
            internal_db, "mongodb://localhost", refresh_sec=60
        )
        result = fetch_index_correction_status(
            internal_db, "mongodb://localhost", refresh_sec=60
        )

        self.assertEqual(result["indexesBuilt"], 1)
        mock_fetch_dest_indexes.assert_called_once()


class TestBuildLiveMonitorPayloadIndexProgress(unittest.TestCase):
    @patch("lib.live_monitoring.fetch_metadata_status")
    @patch("lib.live_monitoring.fetch_progress")
    def test_skips_metadata_index_progress_when_progress_has_index_building(
        self, mock_fetch_progress, mock_fetch_metadata_status
    ):
        mock_fetch_progress.return_value = (
            {
                "state": "RUNNING",
                "indexBuilding": {
                    "indexesBuilt": 1,
                    "totalIndexesToBuild": 5,
                    "collectionsFinished": 0,
                    "collectionsTotal": 1,
                },
            },
            [],
        )
        mock_fetch_metadata_status.return_value = {
            "state": "RUNNING",
            "buildIndexesRaw": "afterDataCopy",
        }

        build_live_monitor_payload(
            "http://localhost:27182/api/v1/progress",
            "mongodb://localhost",
        )

        mock_fetch_metadata_status.assert_called_once_with(
            "mongodb://localhost",
            index_progress_needed=False,
            verification_progress_needed=True,
        )


class TestBuildLiveMonitorPayloadVerificationProgress(unittest.TestCase):
    @patch("lib.live_monitoring.fetch_metadata_status")
    @patch("lib.live_monitoring.fetch_progress")
    def test_skips_metadata_verification_progress_when_progress_has_verification(
        self, mock_fetch_progress, mock_fetch_metadata_status
    ):
        mock_fetch_progress.return_value = (
            {
                "state": "RUNNING",
                "verification": {
                    "source": {"phase": "stream hashing", "scannedCollectionCount": 1},
                    "destination": {"phase": "stream hashing", "scannedCollectionCount": 1},
                },
            },
            [],
        )
        mock_fetch_metadata_status.return_value = {
            "state": "RUNNING",
            "verificationModeRaw": "startAtCEA",
        }

        build_live_monitor_payload(
            "http://localhost:27182/api/v1/progress",
            "mongodb://localhost",
        )

        mock_fetch_metadata_status.assert_called_once_with(
            "mongodb://localhost",
            index_progress_needed=True,
            verification_progress_needed=False,
        )


class TestIndexBuildPhaseGating(unittest.TestCase):
    def test_is_during_or_after_cea(self):
        self.assertFalse(is_during_or_after_cea("collection copy"))
        self.assertFalse(
            is_during_or_after_cea("waiting to start change event application")
        )
        self.assertTrue(is_during_or_after_cea("change event application"))
        self.assertTrue(is_during_or_after_cea("commit completed"))

    def test_index_build_progress_allowed_after_data_copy(self):
        self.assertFalse(
            index_build_progress_allowed("afterDataCopy", "collection copy")
        )
        self.assertTrue(
            index_build_progress_allowed(
                "afterDataCopy", "change event application"
            )
        )
        self.assertTrue(index_build_progress_allowed("beforeDataCopy", "collection copy"))

    def test_should_suppress_index_build_progress(self):
        self.assertTrue(
            should_suppress_index_build_progress(
                "afterDataCopy", "collection copy"
            )
        )
        self.assertFalse(
            should_suppress_index_build_progress(
                "afterDataCopy", "change event application"
            )
        )
        self.assertFalse(
            should_suppress_index_build_progress("beforeDataCopy", "collection copy")
        )


class TestBuildIndexBuildingFromMetadata(unittest.TestCase):
    def test_builds_progress_card_with_metadata_built_counts(self):
        metadata = {
            "buildIndexesRaw": "afterDataCopy",
            "syncPhase": "change event application",
            "indexCollectionsTotal": 3,
            "indexIndexesTotal": 12,
            "indexIndexesBuilt": 5,
            "indexCollectionsFinished": 1,
        }
        card = _build_index_building_from_metadata(metadata)
        self.assertNotIn("mode", card)
        self.assertIn("metadata (approximate)", card["description"])
        self.assertEqual(card["built"], 5)
        self.assertEqual(card["total"], 12)
        self.assertAlmostEqual(card["percent"], 41.7, places=1)
        self.assertEqual(card["metrics"][0]["value"], "5 / 12")
        self.assertEqual(card["metrics"][1]["value"], "1 / 3")

    def test_missing_totals_returns_none(self):
        self.assertIsNone(
            _build_index_building_from_metadata(
                {"buildIndexesRaw": "afterDataCopy", "indexIndexesTotal": 12}
            )
        )

    def test_never_policy_returns_none(self):
        self.assertIsNone(
            _build_index_building_from_metadata(
                {
                    "buildIndexesRaw": "never",
                    "indexCollectionsTotal": 3,
                    "indexIndexesTotal": 12,
                    "indexIndexesBuilt": 5,
                    "indexCollectionsFinished": 1,
                }
            )
        )


    def test_before_cea_after_data_copy_returns_none(self):
        metadata = {
            "buildIndexesRaw": "afterDataCopy",
            "syncPhase": "collection copy",
            "indexCollectionsTotal": 3,
            "indexIndexesTotal": 12,
            "indexIndexesBuilt": 5,
            "indexCollectionsFinished": 1,
        }
        self.assertIsNone(_build_index_building_from_metadata(metadata))


class TestIndexBuildingDisplayIntegration(unittest.TestCase):
    def test_metadata_only_before_cea_shows_info_card_not_progress(self):
        metadata = {
            "state": "RUNNING",
            "phase": "Collection copy",
            "syncPhase": "collection copy",
            "buildIndexesRaw": "afterDataCopy",
            "indexCollectionsTotal": 2,
            "indexIndexesTotal": 10,
            "indexIndexesBuilt": 4,
            "indexCollectionsFinished": 1,
        }
        display = _build_display(None, metadata, progress_available=False)
        self.assertEqual(display["indexBuilding"]["mode"], "info")
        self.assertIn("after the collection copy", display["indexBuilding"]["description"])
        self.assertEqual(display["toolbarBadges"], [])

    def test_metadata_only_at_cea_shows_progress_card(self):
        metadata = {
            "state": "RUNNING",
            "phase": "Change event application",
            "syncPhase": "change event application",
            "buildIndexesRaw": "afterDataCopy",
            "indexCollectionsTotal": 2,
            "indexIndexesTotal": 10,
            "indexIndexesBuilt": 4,
            "indexCollectionsFinished": 1,
        }
        display = _build_display(None, metadata, progress_available=False)
        self.assertNotIn("mode", display["indexBuilding"])
        self.assertIn("metadata (approximate)", display["indexBuilding"]["description"])
        self.assertEqual(display["indexBuilding"]["built"], 4)
        self.assertEqual(display["indexBuilding"]["total"], 10)
        self.assertGreater(display["indexBuilding"]["percent"], 0)

    def test_metadata_totals_win_over_policy_info_card_at_cea(self):
        metadata = {
            "state": "RUNNING",
            "syncPhase": "change event application",
            "buildIndexesRaw": "afterDataCopy",
            "indexCollectionsTotal": 1,
            "indexIndexesTotal": 4,
            "indexIndexesBuilt": 2,
            "indexCollectionsFinished": 0,
        }
        display = _build_display(None, metadata, progress_available=False)
        self.assertNotIn("mode", display["indexBuilding"])
        self.assertEqual(display["indexBuilding"]["built"], 2)

    def test_progress_endpoint_suppressed_before_cea_when_phase_known(self):
        progress = {
            "state": "RUNNING",
            "indexBuilding": {
                "indexesBuilt": 3,
                "totalIndexesToBuild": 10,
                "collectionsFinished": 1,
                "collectionsTotal": 2,
            },
        }
        metadata = {
            "buildIndexesRaw": "afterDataCopy",
            "syncPhase": "collection copy",
        }
        display = _build_display(progress, metadata, progress_available=True)
        self.assertEqual(display["indexBuilding"]["mode"], "info")
        self.assertEqual(display["toolbarBadges"], [])

    def test_progress_endpoint_allowed_at_cea(self):
        progress = {
            "state": "RUNNING",
            "indexBuilding": {
                "indexesBuilt": 3,
                "totalIndexesToBuild": 10,
                "collectionsFinished": 1,
                "collectionsTotal": 2,
            },
        }
        metadata = {
            "buildIndexesRaw": "afterDataCopy",
            "syncPhase": "change event application",
        }
        display = _build_display(progress, metadata, progress_available=True)
        self.assertNotIn("mode", display["indexBuilding"])
        self.assertEqual(
            display["toolbarBadges"],
            [{"label": "INDEXING", "color": "blue"}],
        )

    def test_never_policy_shows_no_card_even_with_totals_in_metadata(self):
        metadata = {
            "state": "RUNNING",
            "buildIndexesRaw": "never",
            "indexCollectionsTotal": 2,
            "indexIndexesTotal": 10,
            "indexIndexesBuilt": 4,
            "indexCollectionsFinished": 1,
        }
        display = _build_display(None, metadata, progress_available=False)
        self.assertIsNone(display["indexBuilding"])

    def test_progress_endpoint_wins_over_metadata_totals(self):
        progress = {
            "state": "RUNNING",
            "indexBuilding": {
                "indexesBuilt": 5,
                "totalIndexesToBuild": 10,
                "collectionsFinished": 1,
                "collectionsTotal": 2,
            },
        }
        metadata = {
            "buildIndexesRaw": "afterDataCopy",
            "syncPhase": "change event application",
            "indexCollectionsTotal": 99,
            "indexIndexesTotal": 99,
            "indexIndexesBuilt": 50,
            "indexCollectionsFinished": 25,
        }
        display = _build_display(progress, metadata, progress_available=True)
        self.assertEqual(display["indexBuilding"]["built"], 5)
        self.assertEqual(display["indexBuilding"]["total"], 10)
        self.assertNotIn("metadata (approximate)", display["indexBuilding"]["description"])


if __name__ == "__main__":
    unittest.main()
