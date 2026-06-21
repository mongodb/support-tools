"""Tests for Embedded Verifier card from globalState.verificationMode."""

import unittest

from lib.live_metadata_status import describe_verification_mode
from lib.live_monitoring import (
    _build_display,
    _build_toolbar_badges,
    _build_verification_info,
    _index_build_activity_active,
    _progress_has_verification_data,
    _resolve_verification_display,
    _verification_activity_active,
    _verification_side_complete,
)


class TestDescribeVerificationMode(unittest.TestCase):
    def test_disabled(self):
        self.assertEqual(
            describe_verification_mode("disabled"),
            "The embedded verifier is disabled.",
        )

    def test_start_at_cea(self):
        self.assertEqual(
            describe_verification_mode("startAtCEA"),
            "Verification will start at the change event application (CEA) phase.",
        )

    def test_start_at_cea_case_insensitive(self):
        self.assertEqual(
            describe_verification_mode("startatCEA"),
            "Verification will start at the change event application (CEA) phase.",
        )

    def test_normalize_verification_mode(self):
        from lib.live_metadata_status import normalize_verification_mode, read_verification_mode_from_global_state

        self.assertEqual(normalize_verification_mode("startatCEA"), "startAtCEA")
        self.assertEqual(
            read_verification_mode_from_global_state({"verificationmode": "startAtCEA"}),
            "startAtCEA",
        )

    def test_unknown_or_missing_returns_none(self):
        self.assertIsNone(describe_verification_mode(None))
        self.assertIsNone(describe_verification_mode(""))
        self.assertIsNone(describe_verification_mode("enabled"))


class TestProgressHasVerificationData(unittest.TestCase):
    def test_empty_or_missing(self):
        self.assertFalse(_progress_has_verification_data(None))
        self.assertFalse(_progress_has_verification_data({}))
        self.assertFalse(_progress_has_verification_data({"verification": {}}))

    def test_with_source_or_destination(self):
        self.assertTrue(
            _progress_has_verification_data(
                {"verification": {"source": {"phase": "scanning"}}}
            )
        )
        self.assertTrue(
            _progress_has_verification_data(
                {"verification": {"destination": {"phase": "scanning"}}}
            )
        )


class TestVerificationInfoCard(unittest.TestCase):
    def test_build_verification_info_disabled(self):
        card = _build_verification_info({"verificationModeRaw": "disabled"})
        self.assertEqual(card["mode"], "info")
        self.assertEqual(card["title"], "Embedded Verifier")
        self.assertIn("disabled", card["description"])

    def test_build_verification_info_unknown_mode(self):
        self.assertIsNone(_build_verification_info({"verificationModeRaw": "enabled"}))


class TestResolveVerificationDisplay(unittest.TestCase):
    def test_disabled_always_info(self):
        progress = {
            "verification": {
                "source": {"phase": "scanning"},
                "destination": {"phase": "scanning"},
            }
        }
        metadata = {"verificationModeRaw": "disabled"}
        card = _resolve_verification_display(
            progress, metadata, progress_available=True
        )
        self.assertEqual(card["mode"], "info")
        self.assertIn("disabled", card["description"])

    def test_start_at_cea_without_progress_data(self):
        metadata = {"verificationModeRaw": "startAtCEA"}
        card = _resolve_verification_display(
            {"state": "RUNNING"}, metadata, progress_available=True
        )
        self.assertEqual(card["mode"], "info")
        self.assertIn("CEA", card["description"])

    def test_start_at_cea_with_progress_data(self):
        progress = {
            "verification": {
                "source": {"phase": "scanning", "scannedCollectionCount": 1},
                "destination": {"phase": "scanning", "scannedCollectionCount": 1},
            }
        }
        metadata = {"verificationModeRaw": "startAtCEA"}
        card = _resolve_verification_display(
            progress, metadata, progress_available=True
        )
        self.assertNotIn("mode", card)
        self.assertIn("source", card)

    def test_no_mode_no_progress_returns_none(self):
        self.assertIsNone(
            _resolve_verification_display(
                {"state": "RUNNING"}, None, progress_available=True
            )
        )


class TestVerificationDisplayIntegration(unittest.TestCase):
    def test_metadata_only_disabled(self):
        metadata = {"state": "RUNNING", "verificationModeRaw": "disabled"}
        display = _build_display(None, metadata, progress_available=False)
        self.assertEqual(display["verification"]["mode"], "info")
        self.assertIn("disabled", display["verification"]["description"])

    def test_metadata_only_start_at_cea(self):
        metadata = {"state": "RUNNING", "verificationModeRaw": "startAtCEA"}
        display = _build_display(None, metadata, progress_available=False)
        self.assertEqual(display["verification"]["mode"], "info")
        self.assertIn("CEA", display["verification"]["description"])

    def test_no_verification_mode_no_card(self):
        metadata = {"state": "RUNNING"}
        display = _build_display(None, metadata, progress_available=False)
        self.assertIsNone(display["verification"])


class TestVerifierPersistenceFallbackDisplay(unittest.TestCase):
    _VERIFICATION_PROGRESS = {
        "source": {
            "phase": "initial hashing",
            "scannedCollectionCount": 1,
            "totalCollectionCount": 3,
            "hashedDocumentCount": 500,
        },
        "destination": {
            "phase": "initial hashing",
            "scannedCollectionCount": 0,
            "totalCollectionCount": 3,
            "hashedDocumentCount": 480,
        },
    }

    def test_start_at_cea_before_cea_shows_info_not_persistence(self):
        metadata = {
            "state": "RUNNING",
            "verificationModeRaw": "startAtCEA",
            "syncPhase": "collection copy",
            "verificationProgress": self._VERIFICATION_PROGRESS,
        }
        display = _build_display(None, metadata, progress_available=False)
        self.assertEqual(display["verification"]["mode"], "info")
        self.assertEqual(display["toolbarBadges"], [])

    def test_start_at_cea_at_cea_shows_persistence_progress(self):
        metadata = {
            "state": "RUNNING",
            "verificationModeRaw": "startAtCEA",
            "syncPhase": "change event application",
            "verificationProgress": self._VERIFICATION_PROGRESS,
        }
        display = _build_display(None, metadata, progress_available=False)
        self.assertNotIn("mode", display["verification"])
        self.assertIn("persistence metadata", display["verification"]["description"])
        self.assertEqual(
            display["verification"]["source"][1]["value"],
            "1 / 3",
        )

    def test_progress_endpoint_wins_over_persistence_metadata(self):
        progress = {
            "verification": {
                "source": {"phase": "stream hashing", "scannedCollectionCount": 9},
                "destination": {"phase": "stream hashing", "scannedCollectionCount": 9},
            }
        }
        metadata = {
            "verificationModeRaw": "startAtCEA",
            "syncPhase": "change event application",
            "verificationProgress": self._VERIFICATION_PROGRESS,
        }
        display = _build_display(progress, metadata, progress_available=True)
        self.assertNotIn("persistence metadata", display["verification"]["description"])

    def test_verifying_badge_from_metadata_persistence_only(self):
        metadata = {
            "state": "RUNNING",
            "verificationModeRaw": "startAtCEA",
            "syncPhase": "change event application",
            "verificationProgress": self._VERIFICATION_PROGRESS,
        }
        display = _build_display(None, metadata, progress_available=False)
        self.assertEqual(
            display["toolbarBadges"],
            [{"label": "VERIFYING", "color": "blue"}],
        )


class TestVerificationSideComplete(unittest.TestCase):
    def test_complete_by_document_counts(self):
        self.assertTrue(
            _verification_side_complete(
                {"hashedDocumentCount": 100, "estimatedDocumentCount": 100}
            )
        )

    def test_incomplete_by_document_counts(self):
        self.assertFalse(
            _verification_side_complete(
                {"hashedDocumentCount": 50, "estimatedDocumentCount": 100}
            )
        )

    def test_complete_by_phase_fallback(self):
        self.assertTrue(_verification_side_complete({"phase": "complete"}))

    def test_inactive_side_ignored(self):
        self.assertIsNone(_verification_side_complete({"phase": "not started"}))

    def test_active_phase_without_counts_is_incomplete(self):
        self.assertFalse(_verification_side_complete({"phase": "scanning"}))


class TestToolbarBadges(unittest.TestCase):
    def test_verifying_badge_when_verifier_in_progress(self):
        progress = {
            "state": "RUNNING",
            "info": "verifier phase",
            "verification": {
                "source": {
                    "phase": "scanning",
                    "hashedDocumentCount": 10,
                    "estimatedDocumentCount": 100,
                },
                "destination": {
                    "phase": "scanning",
                    "hashedDocumentCount": 5,
                    "estimatedDocumentCount": 100,
                },
            },
        }
        metadata = {"verificationModeRaw": "startAtCEA"}

        display = _build_display(progress, metadata, progress_available=True)

        self.assertEqual(display["stateBadge"]["label"], "RUNNING")
        self.assertEqual(display["stateBadge"]["color"], "green")
        self.assertEqual(
            display["toolbarBadges"],
            [{"label": "VERIFYING", "color": "blue"}],
        )

    def test_no_verifying_badge_when_both_sides_complete(self):
        progress = {
            "state": "RUNNING",
            "verification": {
                "source": {
                    "phase": "complete",
                    "hashedDocumentCount": 100,
                    "estimatedDocumentCount": 100,
                },
                "destination": {
                    "phase": "complete",
                    "hashedDocumentCount": 50,
                    "estimatedDocumentCount": 50,
                },
            },
        }
        metadata = {"verificationModeRaw": "startAtCEA"}

        display = _build_display(progress, metadata, progress_available=True)

        self.assertEqual(display["stateBadge"]["label"], "RUNNING")
        self.assertEqual(display["toolbarBadges"], [])

    def test_no_verifying_badge_for_info_card(self):
        metadata = {"state": "RUNNING", "verificationModeRaw": "startAtCEA"}
        display = _build_display({"state": "RUNNING"}, metadata, progress_available=True)

        self.assertEqual(display["verification"]["mode"], "info")
        self.assertEqual(display["toolbarBadges"], [])

    def test_indexing_badge_when_indexes_incomplete(self):
        progress = {
            "state": "RUNNING",
            "indexBuilding": {
                "indexesBuilt": 3,
                "totalIndexesToBuild": 10,
                "collectionsFinished": 1,
                "collectionsTotal": 2,
            },
        }
        metadata = {"buildIndexesRaw": "afterDataCopy", "syncPhase": "change event application"}

        display = _build_display(progress, metadata, progress_available=True)

        self.assertEqual(
            display["toolbarBadges"],
            [{"label": "INDEXING", "color": "blue"}],
        )

    def test_no_indexing_badge_for_info_card(self):
        metadata = {
            "state": "RUNNING",
            "buildIndexesRaw": "afterDataCopy",
        }
        display = _build_display(None, metadata, progress_available=False)

        self.assertEqual(display["indexBuilding"]["mode"], "info")
        self.assertEqual(display["toolbarBadges"], [])

    def test_both_verifying_and_indexing_badges(self):
        progress = {
            "state": "RUNNING",
            "verification": {
                "source": {
                    "phase": "scanning",
                    "hashedDocumentCount": 1,
                    "estimatedDocumentCount": 10,
                },
                "destination": {
                    "phase": "scanning",
                    "hashedDocumentCount": 1,
                    "estimatedDocumentCount": 10,
                },
            },
            "indexBuilding": {
                "indexesBuilt": 1,
                "totalIndexesToBuild": 5,
                "collectionsFinished": 0,
                "collectionsTotal": 1,
            },
        }
        metadata = {
            "verificationModeRaw": "startAtCEA",
            "buildIndexesRaw": "afterDataCopy",
            "syncPhase": "change event application",
        }

        display = _build_display(progress, metadata, progress_available=True)

        self.assertEqual(display["stateBadge"]["label"], "RUNNING")
        self.assertEqual(len(display["toolbarBadges"]), 2)
        self.assertEqual(display["toolbarBadges"][0]["label"], "VERIFYING")
        self.assertEqual(display["toolbarBadges"][1]["label"], "INDEXING")

    def test_build_toolbar_badges_helpers(self):
        verification_card = {"title": "Embedded Verifier", "source": [], "destination": []}
        index_card = {"built": 2, "total": 10, "percent": 20.0}
        progress = {
            "verification": {
                "source": {"phase": "scanning", "hashedDocumentCount": 1, "estimatedDocumentCount": 5}
            }
        }

        self.assertTrue(_verification_activity_active(progress, verification_card))
        self.assertTrue(_index_build_activity_active(index_card))
        self.assertEqual(
            _build_toolbar_badges(progress, verification_card, index_card),
            [
                {"label": "VERIFYING", "color": "blue"},
                {"label": "INDEXING", "color": "blue"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
