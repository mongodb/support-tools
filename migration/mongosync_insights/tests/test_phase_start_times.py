"""Tests for phase start times in Live Monitoring."""

import unittest
from datetime import datetime, timezone

from bson import Timestamp

from lib.live_metadata_status import format_phase_transition_rows, get_phase_transition_series
from lib.live_monitoring import _build_phase_start_times, _build_sync_card


class TestPhaseTransitionRows(unittest.TestCase):
    def test_format_phase_transition_rows_bson_timestamp(self):
        ts = Timestamp(1710000000, 0)
        rows = format_phase_transition_rows(
            [{"phase": "collection copy", "ts": ts}]
        )
        expected = datetime.fromtimestamp(ts.time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["phase"], "Collection copy")
        self.assertEqual(rows[0]["startedAt"], expected)

    def test_format_phase_transition_rows_naive_datetime(self):
        dt = datetime(2024, 6, 15, 10, 30, 45)
        rows = format_phase_transition_rows(
            [{"phase": "change event application", "ts": dt}]
        )
        self.assertEqual(rows[0]["phase"], "Change event application")
        self.assertEqual(rows[0]["startedAt"], "2024-06-15 10:30:45")

    def test_format_phase_transition_rows_missing_ts(self):
        rows = format_phase_transition_rows([{"phase": "commit"}])
        self.assertEqual(rows[0]["startedAt"], "—")

    def test_get_phase_transition_series_empty(self):
        phases, dts = get_phase_transition_series([])
        self.assertEqual(phases, [])
        self.assertEqual(dts, [])


class TestSyncCardPhaseStartTimes(unittest.TestCase):
    def test_includes_phase_start_times_when_metadata_has_transitions(self):
        metadata = {
            "phase": "Collection copy",
            "phaseTransitions": [
                {"phase": "Collection copy", "startedAt": "2024-01-01 00:00:00"},
                {"phase": "Change event application", "startedAt": "2024-01-02 00:00:00"},
            ],
        }
        sync = _build_sync_card(metadata=metadata, progress_available=False)
        self.assertIsNotNone(sync["phaseStartTimes"])
        self.assertEqual(sync["phaseStartTimes"]["label"], "Phase start times")
        self.assertEqual(len(sync["phaseStartTimes"]["rows"]), 2)
        self.assertEqual(sync["phaseStartTimes"]["timezoneNote"], "UTC")

    def test_omits_phase_start_times_without_metadata(self):
        sync = _build_sync_card(metadata=None, progress_available=False)
        self.assertIsNone(sync["phaseStartTimes"])

    def test_omits_phase_start_times_when_transitions_empty(self):
        metadata = {"phase": "Collection copy", "phaseTransitions": []}
        sync = _build_sync_card(metadata=metadata, progress_available=False)
        self.assertIsNone(sync["phaseStartTimes"])

    def test_build_phase_start_times_helper(self):
        metadata = {
            "phaseTransitions": [
                {"phase": "Initializing collections and indexes", "startedAt": "2024-01-01 00:00:00"}
            ]
        }
        result = _build_phase_start_times(metadata)
        self.assertEqual(result["rows"][0]["phase"], "Initializing collections and indexes")


if __name__ == "__main__":
    unittest.main()
