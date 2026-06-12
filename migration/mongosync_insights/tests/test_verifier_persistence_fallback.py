"""Tests for embedded verifier progress from verifier persistence metadata."""

import unittest
from unittest.mock import MagicMock, patch

from lib.live_verifier_metadata import (
    _rollup_cv_phases,
    fetch_verifier_persistence_status,
)


class TestRollupCvPhases(unittest.TestCase):
    def test_empty_docs_not_started(self):
        self.assertEqual(
            _rollup_cv_phases([]),
            {
                "phase": "not started",
                "scannedCollectionCount": None,
                "totalCollectionCount": None,
            },
        )

    def test_all_not_started(self):
        docs = [{"phase": "not started"}, {"phase": "not started"}]
        self.assertEqual(
            _rollup_cv_phases(docs),
            {
                "phase": "not started",
                "scannedCollectionCount": 0,
                "totalCollectionCount": 2,
            },
        )

    def test_all_stream_hashing(self):
        docs = [{"phase": "stream hashing"}, {"phase": "stream hashing"}]
        self.assertEqual(
            _rollup_cv_phases(docs),
            {
                "phase": "stream hashing",
                "scannedCollectionCount": 2,
                "totalCollectionCount": 2,
            },
        )

    def test_mixed_reports_initial_hashing(self):
        docs = [
            {"phase": "stream hashing"},
            {"phase": "initial hashing"},
            {"phase": "not started"},
        ]
        self.assertEqual(
            _rollup_cv_phases(docs),
            {
                "phase": "initial hashing",
                "scannedCollectionCount": 1,
                "totalCollectionCount": 3,
            },
        )


class TestFetchVerifierPersistenceStatus(unittest.TestCase):
    def _mock_db(self, cv_docs, checksum_total):
        db = MagicMock()
        db.list_collection_names.return_value = [
            "collection_verification",
            "collection_checksum",
        ]
        db.__getitem__ = MagicMock(
            side_effect=lambda name: {
                "collection_verification": MagicMock(
                    find=MagicMock(return_value=cv_docs)
                ),
                "collection_checksum": MagicMock(
                    aggregate=MagicMock(
                        return_value=[{"total": checksum_total}] if checksum_total is not None else []
                    )
                ),
            }[name]
        )
        return db

    @patch("lib.app_config.get_database")
    def test_returns_both_sides(self, mock_get_database):
        src_db = self._mock_db([{"phase": "stream hashing"}], 100)
        dst_db = self._mock_db([{"phase": "initial hashing"}], 50)
        mock_get_database.side_effect = [src_db, dst_db]

        result = fetch_verifier_persistence_status("mongodb://localhost")

        self.assertEqual(
            result,
            {
                "source": {
                    "phase": "stream hashing",
                    "totalCollectionCount": 1,
                    "scannedCollectionCount": 1,
                    "hashedDocumentCount": 100,
                },
                "destination": {
                    "phase": "initial hashing",
                    "totalCollectionCount": 1,
                    "scannedCollectionCount": 0,
                    "hashedDocumentCount": 50,
                },
            },
        )

    @patch("lib.app_config.get_database")
    def test_returns_none_when_no_persistence_data(self, mock_get_database):
        empty_db = MagicMock()
        empty_db.list_collection_names.return_value = []
        mock_get_database.side_effect = [empty_db, empty_db]

        self.assertIsNone(fetch_verifier_persistence_status("mongodb://localhost"))

    @patch("lib.app_config.get_database")
    def test_empty_cv_docs_reports_not_started(self, mock_get_database):
        db = self._mock_db([], None)
        mock_get_database.side_effect = [db, MagicMock(list_collection_names=MagicMock(return_value=[]))]

        result = fetch_verifier_persistence_status("mongodb://localhost")

        self.assertEqual(result, {"source": {"phase": "not started"}})

    def test_returns_none_without_connection_string(self):
        self.assertIsNone(fetch_verifier_persistence_status(None))


if __name__ == "__main__":
    unittest.main()
