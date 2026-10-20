#!/usr/bin/env python3
"""Tests for safe mongosh script generation from log-derived namespaces."""

from __future__ import annotations

import argparse
import json
import shlex
import tempfile
import unittest
from pathlib import Path

from datetime import datetime, timedelta, timezone

from cea_low_parallelization_source_times import (
    HOT_MSG,
    PROGRESS_MSG,
    analyze_files,
    annotate_warning_appliers,
    collect_num_processor_samples,
    is_mongosync_log_name,
    iter_log_paths,
    mongosh_command,
    namespace_filename_stem,
    parse_appliers,
    resolve_num_processors,
    safe_filename_part,
    write_scripts,
)


def _progress(time: str, lag_secs: int, *, mongosync_id: str = "ms-1") -> str:
    return json.dumps(
        {
            "time": time,
            "message": PROGRESS_MSG,
            "mongosyncID": mongosync_id,
            "lag": {"crudLagSeconds": lag_secs},
            "lastAppliedCrudTs": {"T": 1, "I": 1},
        }
    )


def _warning(
    time: str,
    ns: str,
    *,
    mongosync_id: str = "ms-1",
    spread: int = 20,
) -> str:
    return json.dumps(
        {
            "time": time,
            "message": HOT_MSG,
            "mongosyncID": mongosync_id,
            "recentCRUDStatistics": {
                "namespace": ns,
                "spreadDisparity": spread,
                "totalEvents": 1000,
                "estimatedUniqueDocuments": 1000,
            },
        }
    )


def _cea_memory(time: str, num_processors: int, *, mongosync_id: str = "ms-1") -> str:
    return json.dumps(
        {
            "time": time,
            "mongosyncID": mongosync_id,
            "ceaMemoryUsage": {
                "dispatcherToProcessorChannels": {"numProcessors": num_processors}
            },
        }
    )


class ResolveNumProcessorsTests(unittest.TestCase):
    def test_uses_latest_sample_at_or_before_warning_per_instance(self) -> None:
        t0 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        samples = {
            "a": [(t0, 16), (t2, 32)],
            "b": [(t0, 256), (t0, 256), (t0, 256)],  # more samples, must not win for A
        }
        self.assertEqual(resolve_num_processors(samples, "a", t1), 16)
        self.assertEqual(resolve_num_processors(samples, "a", t2), 32)
        self.assertEqual(resolve_num_processors(samples, "b", t1), 256)

    def test_mixed_instances_do_not_share_global_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_a = root / "a.log"
            log_b = root / "b.log"
            log_a.write_text(
                "\n".join(
                    [
                        _cea_memory("2026-01-01T10:00:00Z", 16, mongosync_id="a"),
                        _progress("2026-01-01T10:00:00Z", 0, mongosync_id="a"),
                        _warning("2026-01-01T10:05:00Z", "db.from_a", mongosync_id="a"),
                    ]
                )
                + "\n"
            )
            # Many more B samples at 256 — old global mode would pick 256 for everyone.
            log_b.write_text(
                "\n".join(
                    [_cea_memory("2026-01-01T10:00:00Z", 256, mongosync_id="b")] * 5
                    + [
                        _progress("2026-01-01T10:00:00Z", 0, mongosync_id="b"),
                        _warning("2026-01-01T10:05:00Z", "db.from_b", mongosync_id="b"),
                    ]
                )
                + "\n"
            )
            result = analyze_files([log_a, log_b], set())
            samples = collect_num_processor_samples([log_a, log_b])
            annotate_warning_appliers(result, samples)
            by_ns = {s["namespace"]: s for s in result["namespaces"]}
            self.assertEqual(by_ns["db.from_a"]["warnings"][0]["inferredAppliers"], 16)
            self.assertEqual(by_ns["db.from_b"]["warnings"][0]["inferredAppliers"], 256)

            out = root / "scripts"
            write_scripts(
                result,
                out,
                appliers_override=None,
                margin=timedelta(minutes=5),
                gap=timedelta(minutes=30),
                js_path=None,
            )
            sh_texts = "\n".join(p.read_text() for p in out.glob("*.sh"))
            self.assertIn("appliers: 16", sh_texts)
            self.assertIn("appliers: 256", sh_texts)


class AnalyzeFilesChronologyTests(unittest.TestCase):
    def test_out_of_order_files_use_prior_progress_not_future(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Newest file first in path list (as directory mode often does).
            current = root / "mongosync.log"
            older = root / "mongosync-2026-01-01T10-00-00.000.log"
            current.write_text(
                "\n".join(
                    [
                        _progress("2026-01-01T12:00:00Z", 60),
                        _warning("2026-01-01T12:05:00Z", "db.late"),
                    ]
                )
                + "\n"
            )
            older.write_text(
                "\n".join(
                    [
                        _progress("2026-01-01T10:00:00Z", 3600),
                        _warning("2026-01-01T10:05:00Z", "db.early"),
                    ]
                )
                + "\n"
            )
            # Process newest before oldest — the bug scenario.
            result = analyze_files([current, older], set())
            by_ns = {s["namespace"]: s for s in result["namespaces"]}
            early = by_ns["db.early"]["warnings"][0]
            late = by_ns["db.late"]["warnings"][0]
            self.assertEqual(early["lagSeconds"], 3600)
            self.assertEqual(early["lagAgeSeconds"], 300.0)
            self.assertTrue(early["lagAgeSeconds"] >= 0)
            self.assertEqual(late["lagSeconds"], 60)
            self.assertEqual(late["lagAgeSeconds"], 300.0)

    def test_lag_not_shared_across_mongosync_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mongosync.log"
            path.write_text(
                "\n".join(
                    [
                        _progress("2026-01-01T10:00:00Z", 100, mongosync_id="a"),
                        _progress("2026-01-01T10:00:00Z", 9999, mongosync_id="b"),
                        _warning("2026-01-01T10:01:00Z", "db.from_a", mongosync_id="a"),
                        _warning("2026-01-01T10:01:00Z", "db.from_b", mongosync_id="b"),
                    ]
                )
                + "\n"
            )
            result = analyze_files([path], set())
            by_ns = {s["namespace"]: s for s in result["namespaces"]}
            self.assertEqual(by_ns["db.from_a"]["warnings"][0]["lagSeconds"], 100)
            self.assertEqual(by_ns["db.from_b"]["warnings"][0]["lagSeconds"], 9999)


class IsMongosyncLogNameTests(unittest.TestCase):
    def test_current_and_rotated(self) -> None:
        for name in (
            "mongosync.log",
            "mongosync.log.1",
            "mongosync.log.2",
            "mongosync.log.gz",
            "mongosync.log.1.gz",
            "mongosync-shard0.log",
            "mongosync-shard0.log.3.gz",
        ):
            self.assertTrue(is_mongosync_log_name(name), name)

    def test_rejects_metrics_and_unrelated(self) -> None:
        for name in (
            "mongosync_metrics.log",
            "mongosync_metrics_22JUN2026.log",
            "myfile.log",
            "mongosync.log.bak",
            "mongosync.txt",
        ):
            self.assertFalse(is_mongosync_log_name(name), name)


class IterLogPathsTests(unittest.TestCase):
    def test_directory_includes_rotated_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in (
                "mongosync.log",
                "mongosync.log.1",
                "mongosync.log.1.gz",
                "mongosync_metrics.log",
                "readme.txt",
            ):
                (root / name).write_text("")
            found = {p.name for p in iter_log_paths([tmp])}
            self.assertEqual(
                found,
                {"mongosync.log", "mongosync.log.1", "mongosync.log.1.gz"},
            )


class ParseAppliersTests(unittest.TestCase):
    def test_zero_means_auto_detect(self) -> None:
        self.assertEqual(parse_appliers("0"), 0)

    def test_accepts_two_or_more(self) -> None:
        self.assertEqual(parse_appliers("2"), 2)
        self.assertEqual(parse_appliers("256"), 256)

    def test_rejects_one(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_appliers("1")

    def test_rejects_negative(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_appliers("-1")


class SafeFilenamePartTests(unittest.TestCase):
    def test_keeps_normal_namespace(self) -> None:
        self.assertEqual(safe_filename_part("mydb.events"), "mydb.events")

    def test_replaces_path_and_shell_chars(self) -> None:
        self.assertEqual(safe_filename_part("../a';b$(x)"), "a_b_x")

    def test_namespace_stem_disambiguates_sanitizer_collisions(self) -> None:
        slash = "db.a/b"
        underscore = "db.a_b"
        self.assertEqual(safe_filename_part(slash), safe_filename_part(underscore))
        self.assertNotEqual(
            namespace_filename_stem(slash),
            namespace_filename_stem(underscore),
        )
        self.assertTrue(namespace_filename_stem(slash).startswith("db.a_b-"))
        self.assertTrue(namespace_filename_stem(underscore).startswith("db.a_b-"))


class MongoshCommandTests(unittest.TestCase):
    def _eval_payload(self, command: str) -> str:
        # Join continued lines the way a shell would before splitting.
        joined = command.replace("\\\n", "")
        argv = shlex.split(joined)
        self.assertIn("--eval", argv)
        return argv[argv.index("--eval") + 1]

    def _output_file(self, payload: str) -> str:
        marker = 'outputFile: "'
        start = payload.index(marker) + len(marker)
        end = payload.index('"', start)
        return payload[start:end]

    def test_normal_namespace(self) -> None:
        ns = "mydb.events"
        cmd = mongosh_command(ns, "2026-01-01T00:00:00Z", "20260101T0000Z", 16)
        payload = self._eval_payload(cmd)
        self.assertIn(json.dumps(ns), payload)
        self.assertIn(json.dumps("2026-01-01T00:00:00Z"), payload)
        self.assertEqual(
            self._output_file(payload),
            f"hot-doc-spread-check-{namespace_filename_stem(ns)}-20260101T0000Z.json",
        )

    def test_apostrophe_and_shell_metacharacters_do_not_break_eval(self) -> None:
        ns = "db.coll';$(id); echo pwned #"
        cmd = mongosh_command(ns, "2026-01-01T00:00:00Z", "20260101T0000Z", 8)
        argv = shlex.split(cmd.replace("\\\n", ""))
        payload = argv[argv.index("--eval") + 1]
        # Still a single --eval argument; namespace round-trips as a JS/JSON string.
        self.assertIn(json.dumps(ns), payload)
        self.assertEqual(argv[0], "mongosh")
        self.assertNotIn("echo", argv)
        # Filename uses sanitized namespace + digest; raw ns only inside JSON string.
        self.assertEqual(
            self._output_file(payload),
            f"hot-doc-spread-check-{namespace_filename_stem(ns)}-20260101T0000Z.json",
        )

    def test_quote_and_newline_in_namespace(self) -> None:
        ns = 'db.coll"\nfoo'
        cmd = mongosh_command(ns, "2026-01-01T00:00:00Z", "20260101T0000Z", 4)
        payload = self._eval_payload(cmd)
        self.assertIn(json.dumps(ns), payload)

    def test_colliding_sanitized_namespaces_get_distinct_output_files(self) -> None:
        tag = "20260101T0000Z"
        slash = mongosh_command("db.a/b", "2026-01-01T00:00:00Z", tag, 16)
        underscore = mongosh_command("db.a_b", "2026-01-01T00:00:00Z", tag, 16)
        out_slash = self._output_file(self._eval_payload(slash))
        out_underscore = self._output_file(self._eval_payload(underscore))
        self.assertNotEqual(out_slash, out_underscore)
        self.assertEqual(
            out_slash,
            f"hot-doc-spread-check-{namespace_filename_stem('db.a/b')}-{tag}.json",
        )
        self.assertEqual(
            out_underscore,
            f"hot-doc-spread-check-{namespace_filename_stem('db.a_b')}-{tag}.json",
        )


if __name__ == "__main__":
    unittest.main()
