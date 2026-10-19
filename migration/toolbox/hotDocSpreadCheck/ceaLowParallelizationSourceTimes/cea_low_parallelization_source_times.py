#!/usr/bin/env python3
"""Find mongosync CEA low-parallelization warnings and estimate when the writes happened on source.

Mongosync logs the warning at apply time. Source time is reconstructed as:

    warning_time - lag.crudLagSeconds

(falling back to lag.overallLagSeconds). That is about minute-accurate, not second-accurate.

The warning fires when a 10s collection window has spreadDisparity > 10 and totalEvents >= 1000.

Usage:
  python3 cea_low_parallelization_source_times.py /path/to/mongosync.log /path/to/logs/*.gz
  python3 cea_low_parallelization_source_times.py /path/to/logdir --ignore db.noisyCollection
  python3 cea_low_parallelization_source_times.py ./mongosync.log --json
  python3 cea_low_parallelization_source_times.py ./logs --write-scripts ./burst-scripts
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import shlex
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOT_MSG = "The level of CEA parallelization for this collection is low"
PROGRESS_MSG = "Replication progress."


def parse_log_time(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_utc(dt: datetime | None) -> str:
    if dt is None:
        return "n/a"
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def fmt_utc_short(dt: datetime | None) -> str:
    if dt is None:
        return "n/a"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def fmt_time_range(start: datetime | None, end: datetime | None) -> str:
    if start is None and end is None:
        return "n/a"
    if start is None:
        return fmt_utc(end)
    if end is None or start == end:
        return fmt_utc(start)
    if start.date() == end.date():
        return (
            f"{start.strftime('%Y-%m-%d')} "
            f"{start.strftime('%H:%M:%S')}–{end.strftime('%H:%M:%S')} UTC"
        )
    return f"{fmt_utc_short(start)} – {fmt_utc(end)}"


def format_op_types(types: dict | None) -> str:
    if not types:
        return ""
    return ", ".join(f"{count} {name}" for name, count in types.items())


def notes_for_namespace(ns: dict) -> str:
    bits = []
    rmin = ns.get("uniquePerEventMin")
    rmax = ns.get("uniquePerEventMax")
    if rmin is not None and rmax is not None:
        if rmin >= 0.995 and rmax >= 0.995:
            bits.append("unique/event = 1.0")
        elif abs(rmin - rmax) < 0.001:
            bits.append(f"unique/event = {rmin:.2f} (some _id reuse)")
        else:
            bits.append(f"unique/event {rmin:.2f}–{rmax:.2f}")
    peak = ns.get("warnings") or []
    if peak:
        top = max(peak, key=lambda r: r.get("spreadDisparity") or 0)
        types = format_op_types(top.get("totalEventsPerType"))
        if types:
            bits.append(types)
    return "; ".join(bits) if bits else ""


def crud_ts_to_datetime(ts: dict | None) -> datetime | None:
    if not ts:
        return None
    t = ts.get("T")
    if t is None:
        return None
    return datetime.fromtimestamp(int(t), tz=timezone.utc)


def open_log(path: Path):
    if path.suffix == ".gz" or path.name.endswith(".log.gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("rt", encoding="utf-8", errors="replace")


# Current, rotated, and gzipped mongosync logs (not metrics exports).
_MONGOSYNC_LOG_NAME = re.compile(
    r"^mongosync.*\.log(\.\d+)?(\.gz)?$",
    re.IGNORECASE,
)


def is_mongosync_log_name(name: str) -> bool:
    """True for mongosync.log, mongosync.log.1, mongosync.log.1.gz, etc."""
    lower = name.lower()
    if "metrics" in lower:
        return False
    return bool(_MONGOSYNC_LOG_NAME.match(name))


def iter_log_paths(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            paths.extend(
                sorted(
                    child
                    for child in p.iterdir()
                    if child.is_file() and is_mongosync_log_name(child.name)
                )
            )
        elif p.is_file():
            paths.append(p)
        else:
            print(f"warning: not found: {p}", file=sys.stderr)
    # Keep user order for files, but sort a directory's matches.
    seen = set()
    unique = []
    for p in paths:
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(p)
    return unique


def lag_seconds(lag: dict | None) -> int | None:
    if not lag:
        return None
    for key in ("crudLagSeconds", "overallLagSeconds"):
        value = lag.get(key)
        if value is not None:
            return int(value)
    return None


def source_from_warning(wall: datetime, lag: dict | None) -> tuple[int | None, datetime | None]:
    secs = lag_seconds(lag)
    if secs is None:
        return None, None
    return secs, wall - timedelta(seconds=secs)


# Progress before warnings at the same timestamp so lag is available immediately.
_KIND_PROGRESS = 0
_KIND_WARNING = 1


def analyze_files(paths: list[Path], ignore: set[str]) -> dict:
    """Parse logs and pair each warning with the latest prior progress lag.

    Records are ordered by (mongosyncID, time), not by file/line order, so
    rotated segments supplied out of order still get correct source times.
    Lag state is never shared across mongosync instances.
    """
    events: dict[str, list[dict]] = defaultdict(list)
    ignored_count = 0
    warning_count = 0
    progress_count = 0
    parse_errors = 0

    # (instance_id, wall, kind, path_name, obj)
    records: list[tuple[str, datetime, int, str, dict]] = []

    for path in paths:
        try:
            fh = open_log(path)
        except OSError as exc:
            print(f"warning: cannot read {path}: {exc}", file=sys.stderr)
            continue
        with fh:
            for line in fh:
                if HOT_MSG not in line and PROGRESS_MSG not in line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                try:
                    wall = parse_log_time(obj["time"])
                except (KeyError, ValueError):
                    parse_errors += 1
                    continue
                msg = obj.get("message") or ""
                instance_id = str(obj.get("mongosyncID") or path.name)
                if msg == PROGRESS_MSG:
                    progress_count += 1
                    records.append((instance_id, wall, _KIND_PROGRESS, path.name, obj))
                    continue
                if HOT_MSG not in msg:
                    continue
                warning_count += 1
                records.append((instance_id, wall, _KIND_WARNING, path.name, obj))

    records.sort(key=lambda r: (r[0], r[1], r[2]))

    last_lag = None
    last_lag_time = None
    last_applied = None
    current_instance: str | None = None

    for instance_id, wall, kind, path_name, obj in records:
        if instance_id != current_instance:
            current_instance = instance_id
            last_lag = None
            last_lag_time = None
            last_applied = None

        if kind == _KIND_PROGRESS:
            last_lag = obj.get("lag") or {}
            last_lag_time = wall
            last_applied = obj.get("lastAppliedCrudTs")
            continue

        stats = obj.get("recentCRUDStatistics") or {}
        ns = stats.get("namespace") or "?"
        if ns in ignore:
            ignored_count += 1
            continue
        total_events = stats.get("totalEvents") or 0
        unique_docs = stats.get("estimatedUniqueDocuments")
        ratio = None
        if unique_docs is not None and total_events:
            ratio = unique_docs / total_events
        lag_secs, source_dt = source_from_warning(wall, last_lag)
        lag_age = None
        if last_lag_time is not None:
            lag_age = (wall - last_lag_time).total_seconds()
        events[ns].append(
            {
                "file": path_name,
                "mongosyncID": instance_id,
                "warningTime": wall.isoformat(),
                "sourceTime": source_dt.isoformat() if source_dt else None,
                "lastAppliedCrudTs": crud_ts_to_datetime(last_applied).isoformat()
                if last_applied
                else None,
                "lagSeconds": lag_secs,
                "lagAgeSeconds": lag_age,
                "spreadDisparity": stats.get("spreadDisparity"),
                "totalEvents": total_events,
                "estimatedUniqueDocuments": unique_docs,
                "uniquePerEvent": ratio,
                "totalEventsPerType": stats.get("totalEventsPerType"),
                "totalAppliers": stats.get("totalAppliers"),
                "busiestAppliers": stats.get("busiestAppliers"),
                "namespace": ns,
            }
        )

    summaries = []
    for ns, recs in events.items():
        recs_sorted = sorted(recs, key=lambda r: r["warningTime"])
        sources = [
            parse_log_time(r["sourceTime"]) for r in recs_sorted if r["sourceTime"]
        ]
        spreads = [r["spreadDisparity"] for r in recs_sorted if r["spreadDisparity"] is not None]
        ratios = [r["uniquePerEvent"] for r in recs_sorted if r["uniquePerEvent"] is not None]
        hours = defaultdict(int)
        for st in sources:
            hours[st.replace(minute=0, second=0, microsecond=0)] += 1
        first, last = recs_sorted[0], recs_sorted[-1]
        peak = max(recs_sorted, key=lambda r: r["spreadDisparity"] or 0)
        summaries.append(
            {
                "namespace": ns,
                "warningCount": len(recs_sorted),
                "files": sorted({r["file"] for r in recs_sorted}),
                "spreadMin": min(spreads) if spreads else None,
                "spreadMax": max(spreads) if spreads else None,
                "uniquePerEventMin": min(ratios) if ratios else None,
                "uniquePerEventMax": max(ratios) if ratios else None,
                "firstWarningTime": first["warningTime"],
                "lastWarningTime": last["warningTime"],
                "firstSourceTime": first["sourceTime"],
                "lastSourceTime": last["sourceTime"],
                "sourceSpanStart": min(sources).isoformat() if sources else None,
                "sourceSpanEnd": max(sources).isoformat() if sources else None,
                "peakSpread": peak["spreadDisparity"],
                "peakWarningTime": peak["warningTime"],
                "peakSourceTime": peak["sourceTime"],
                "sourceHours": [
                    {"hour": h.isoformat(), "warnings": c} for h, c in sorted(hours.items())
                ],
                "warnings": recs_sorted,
            }
        )
    summaries.sort(key=lambda s: s["sourceSpanStart"] or s["firstWarningTime"] or "")

    return {
        "filesScanned": [str(p) for p in paths],
        "progressLines": progress_count,
        "warningsSeen": warning_count,
        "warningsIgnored": ignored_count,
        "parseErrors": parse_errors,
        "note": (
            "sourceTime = warningTime - lag.crudLagSeconds (else overallLagSeconds). "
            "Lag is taken from the latest Replication progress line at or before the warning, "
            "ordered by time within each mongosyncID (not by file order). "
            "This is the approximate oplog time mongosync was applying, not an exact event timestamp. "
            "uniquePerEvent of 1.0 means distinct _ids (bulk insert/delete), not one hot document."
        ),
        "namespaces": summaries,
    }


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    def fmt_row(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells)) + " |"
    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    lines = [fmt_row(headers), sep]
    lines.extend(fmt_row(row) for row in rows)
    return "\n".join(lines)


def print_text(result: dict) -> None:
    print(
        f"Scanned {len(result['filesScanned'])} file(s). "
        f"Warnings: {result['warningsSeen']} "
        f"(ignored {result['warningsIgnored']}). "
        f"Progress lines: {result['progressLines']}."
    )
    print()
    print(
        "Mongosync flagged a collection when a 10s window had "
        "spreadDisparity > 10 and >= 1000 events."
    )
    print(
        "Source time is warning time minus lag.crudLagSeconds "
        "(about the minute, not the exact second)."
    )
    print()
    if not result["namespaces"]:
        print("No matching warnings.")
        return

    rows = []
    for ns in result["namespaces"]:
        warn_start = parse_log_time(ns["firstWarningTime"]) if ns["firstWarningTime"] else None
        warn_end = parse_log_time(ns["lastWarningTime"]) if ns["lastWarningTime"] else None
        src_start = parse_log_time(ns["sourceSpanStart"]) if ns["sourceSpanStart"] else None
        src_end = parse_log_time(ns["sourceSpanEnd"]) if ns["sourceSpanEnd"] else None
        rows.append(
            [
                ns["namespace"],
                str(ns["warningCount"]),
                fmt_time_range(warn_start, warn_end),
                fmt_time_range(src_start, src_end),
                notes_for_namespace(ns),
            ]
        )
    print(
        markdown_table(
            [
                "Namespace",
                "Warnings",
                "Warning (UTC, apply time)",
                "Source writes (UTC)",
                "Notes",
            ],
            rows,
        )
    )
    if result["warningsIgnored"]:
        print()
        print(f"Ignored {result['warningsIgnored']} warning(s) via --ignore.")


def parse_appliers(value: str) -> int:
    """Parse --appliers: 0 means auto-detect; otherwise must be >= 2 (JS contract)."""
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from exc
    if n == 0:
        return 0
    if n < 2:
        raise argparse.ArgumentTypeError(
            "must be an integer >= 2, or 0 to auto-detect from logs "
            "(hot-doc-spread-check.js rejects appliers < 2)"
        )
    return n


def infer_num_processors(paths: list[Path]) -> int | None:
    """Read ceaMemoryUsage.numProcessors without changing the JSON report."""
    counts: dict[int, int] = defaultdict(int)
    for path in paths:
        try:
            fh = open_log(path)
        except OSError:
            continue
        with fh:
            for line in fh:
                if "numProcessors" not in line or "ceaMemoryUsage" not in line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                disp = (obj.get("ceaMemoryUsage") or {}).get("dispatcherToProcessorChannels") or {}
                n = disp.get("numProcessors")
                # Match hot-doc-spread-check.js: appliers must be >= 2.
                if isinstance(n, int) and n >= 2:
                    counts[n] += 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def cluster_source_windows(
    warnings: list[dict],
    gap: timedelta,
) -> list[list[datetime]]:
    times = sorted(
        parse_log_time(w["sourceTime"]) for w in warnings if w.get("sourceTime")
    )
    if not times:
        return []
    windows: list[list[datetime]] = [[times[0]]]
    for ts in times[1:]:
        if ts - windows[-1][-1] > gap:
            windows.append([ts])
        else:
            windows[-1].append(ts)
    return windows


def safe_filename_part(value: str) -> str:
    """Make log-derived strings safe for use in generated filenames."""
    cleaned = re.sub(r"[^\w.\-]+", "_", value, flags=re.UNICODE)
    return cleaned.strip("._-") or "namespace"


def mongosh_command(ns: str, start_iso: str, tag: str, appliers: int) -> str:
    outfile = f"hot-doc-spread-check-{safe_filename_part(ns)}-{tag}.json"
    # Serialize JS string values; shell-quote the whole --eval so log data cannot
    # break out of quotes or inject shell metacharacters.
    eval_js = f"""globalThis.MONITOR_ARGS = {{
    namespaces: [{json.dumps(ns)}],
    lookbackMs: Date.now() - Date.parse({json.dumps(start_iso)}),
    runMs: 1800000,
    appliers: {int(appliers)},
    spreadDisparityThreshold: 5,
    minDocCps: 1,
    minTotalCps: 0,
    topDocCountForProxy: 5,
    idleMs: 2000,
    maxUniqueDocs: 2000000,
    outputFormat: "json",
    outputFile: {json.dumps(outfile)}
  }}"""
    return (
        'mongosh "mongodb://USER:PASSWORD@HOST/admin" \\\n'
        f"  --eval {shlex.quote(eval_js)} \\\n"
        "  --file hot-doc-spread-check.js\n"
    )


def write_scripts(
    result: dict,
    out_dir: Path,
    *,
    appliers: int,
    margin: timedelta,
    gap: timedelta,
    js_path: Path | None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    file_num = 0

    for ns in result["namespaces"]:
        windows = cluster_source_windows(ns["warnings"], gap)
        if not windows:
            print(f"warning: no source times for {ns['namespace']}; skip scripts", file=sys.stderr)
            continue
        commands = []
        stem_tags = []
        for window in windows:
            start = (min(window) - margin).replace(second=0, microsecond=0)
            start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
            tag = start.strftime("%Y%m%dT%H%MZ")
            commands.append(mongosh_command(ns["namespace"], start_iso, tag, appliers))
            stem_tags.append(tag)
        file_num += 1
        safe_ns = safe_filename_part(ns["namespace"])
        if len(stem_tags) == 1:
            stem = f"{safe_ns}-{stem_tags[0]}"
        else:
            stem = safe_ns
        path = out_dir / f"{file_num:02d}-{stem}.sh"
        path.write_text("\n".join(commands).rstrip() + "\n")
        path.chmod(0o755)
        written.append(path)

    js_dest = out_dir / "hot-doc-spread-check.js"
    if js_path and js_path.is_file():
        js_dest.write_text(js_path.read_text())
        written.append(js_dest)
    else:
        print(
            f"warning: hot-doc-spread-check.js not copied (not found at {js_path})",
            file=sys.stderr,
        )

    instructions = f"""Hot Doc Spread Check - historical burst pack
============================================

These scripts open the change stream a few minutes BEFORE each mongosync
low-parallelization window, then stop on idle (2s) or after 30 minutes.

Replace USER, PASSWORD, and HOST. Keep hot-doc-spread-check.js in this directory.

Run oldest first (01, then 02, ...).

lookbackMs is computed at runtime:
  Date.now() - Date.parse("<burst start UTC>")

Settings:
  appliers: {appliers}
  idleMs: 2000
  runMs: 1800000 (30 minutes drain cap)
  maxUniqueDocs: 2000000
  one namespace per file (multiple mongosh calls if the namespace had separate bursts)

Send back the generated hot-doc-spread-check-*.json files.
Do not send the connection string or password.
"""
    instr = out_dir / "INSTRUCTIONS.txt"
    instr.write_text(instructions)
    written.append(instr)
    return written


def default_js_path() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here / "hot-doc-spread-check.js", here.parent / "hot-doc-spread-check.js"):
        if candidate.is_file():
            return candidate
    return here.parent / "hot-doc-spread-check.js"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Estimate source write times for mongosync CEA low-parallelization warnings."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help=(
            "mongosync.log, rotated segments (mongosync.log.1, mongosync.log.1.gz), "
            "or a directory of those files"
        ),
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        help="namespace to skip (repeatable). Example: db.noisyCollection",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print JSON instead of a text summary",
    )
    parser.add_argument(
        "--write-scripts",
        metavar="DIR",
        help="write per-namespace hot-doc-spread-check mongosh scripts into DIR",
    )
    parser.add_argument(
        "--appliers",
        type=parse_appliers,
        default=0,
        help=(
            "appliers value for generated scripts: integer >= 2, or 0 to auto-detect "
            "from ceaMemoryUsage numProcessors (else 256)"
        ),
    )
    parser.add_argument(
        "--lookback-margin-minutes",
        type=int,
        default=5,
        help="minutes before the first source write to open the change stream (default: 5)",
    )
    parser.add_argument(
        "--window-gap-minutes",
        type=int,
        default=30,
        help="source-time gap that starts a new mongosh call in the same namespace file (default: 30)",
    )
    parser.add_argument(
        "--script-js",
        type=Path,
        default=None,
        help="path to hot-doc-spread-check.js to copy into the script directory",
    )
    args = parser.parse_args()
    paths = iter_log_paths(args.paths)
    if not paths:
        print("no log files found", file=sys.stderr)
        return 1
    result = analyze_files(paths, set(args.ignore))
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        print_text(result)

    if args.write_scripts:
        appliers = args.appliers
        if appliers == 0:
            inferred = infer_num_processors(paths)
            appliers = inferred if inferred else 256
            if not args.json:
                print()
                if inferred:
                    print(f"Using appliers={appliers} from ceaMemoryUsage.numProcessors.")
                else:
                    print(f"Using appliers={appliers} (numProcessors not found in logs).")
        written = write_scripts(
            result,
            Path(args.write_scripts),
            appliers=appliers,
            margin=timedelta(minutes=args.lookback_margin_minutes),
            gap=timedelta(minutes=args.window_gap_minutes),
            js_path=args.script_js or default_js_path(),
        )
        if not args.json:
            print()
            print(f"Wrote {len(written)} file(s) to {args.write_scripts}")
            for path in written:
                if path.suffix == ".sh":
                    print(f"  {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
