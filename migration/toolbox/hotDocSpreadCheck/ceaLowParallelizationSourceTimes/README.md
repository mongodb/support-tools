# CEA low-parallelization source times

`cea_low_parallelization_source_times.py` reads mongosync logs, finds Change Event
Application (CEA) low-parallelization warnings, estimates when those writes happened
on the source, and optionally writes one-namespace `hot-doc-spread-check.js` scripts
aimed at those source windows.

Use it when mongosync logged *The level of CEA parallelization for this collection is
low* and you need:

* which namespaces were flagged
* approximately when the source writes occurred (so you can open a change stream there)
* a customer-ready pack of mongosh scripts for `hot-doc-spread-check.js`

It does not connect to MongoDB. It only parses mongosync log files.

## Why source time is estimated

Mongosync emits the warning at **apply time**, not at the source oplog time. While
replication is lagged, apply time can be hours or days after the writes.

The script reconstructs source time as:

```text
sourceTime ≈ warningTime − lag.crudLagSeconds
```

If `crudLagSeconds` is missing, it falls back to `lag.overallLagSeconds`. Lag is
taken from the most recent `Replication progress.` line at or before the warning,
after sorting records by time within each `mongosyncID` (file order does not matter).

This is about **minute-accurate**, not second-accurate. It is the oplog time mongosync
was applying around that warning, not the timestamp of a specific event.

The warning itself fires when a 10-second collection window has `spreadDisparity > 10`
and `totalEvents >= 1000`.

## Requirements

* Python 3.9+ (stdlib only)
* mongosync logs: `mongosync.log`, `mongosync-*.log`, or `mongosync-*.log.gz`
* for `--write-scripts`: `hot-doc-spread-check.js` from the parent folder
* to run the generated scripts: `mongosh` and a source that still has those events
  in the oplog / change stream (typically replica-set oplog retention)

## Usage

From this directory:

```bash
# Text table (default)
python3 cea_low_parallelization_source_times.py /path/to/mongosync.log
python3 cea_low_parallelization_source_times.py /path/to/logdir

# Skip noisy namespaces (repeatable)
python3 cea_low_parallelization_source_times.py /path/to/logdir --ignore db.refData

# Machine-readable report (same schema whether or not you write scripts)
python3 cea_low_parallelization_source_times.py /path/to/logdir --json

# Table plus a customer script pack
python3 cea_low_parallelization_source_times.py /path/to/logdir \
  --ignore db.refData \
  --write-scripts ./burst-scripts
```

A directory argument is scanned for mongosync log files, including rotated
segments (`mongosync.log`, `mongosync.log.1`, `mongosync.log.1.gz`, …). Metrics
exports (`*metrics*`) are skipped.

### Text output

| Column | Meaning |
| --- | --- |
| Namespace | Collection mongosync flagged |
| Warnings | How many low-parallelization lines after `--ignore` |
| Warning (UTC, apply time) | When mongosync logged the warning |
| Source writes (UTC) | Estimated source / oplog window |
| Notes | `unique/event` and the op mix on the peak-spread warning |

`unique/event` is `estimatedUniqueDocuments / totalEvents` from the warning stats:

* **1.0** — almost every event had a distinct `_id` (bulk insert/delete/replace of many
  documents). That is a hash-spread / routing issue, not one hot document.
* **well below 1.0** — the same `_id`s were reused (more consistent with hot documents).

### JSON output

`--json` prints the same analysis object the script always builds. `--write-scripts`
does not add fields to that object. Typical top-level keys:

* `filesScanned`, `progressLines`, `warningsSeen`, `warningsIgnored`, `parseErrors`
* `note` — reminder about how `sourceTime` is derived
* `namespaces[]` — per-collection summary plus the raw `warnings[]` rows

Use JSON when you want to inspect every warning, lag age, or `sourceHours` histogram.

## `--write-scripts`

Creates a directory with:

* `NN-<namespace>-<tag>.sh` — one namespace per file, oldest source window first
* `hot-doc-spread-check.js` — copy of the parent script
* `INSTRUCTIONS.txt` — how to fill in the URI and what to send back

If one namespace has **separate bursts** (source times more than 30 minutes apart),
those become multiple `mongosh` calls in the same file, and the filename drops the
time tag: `NN-<namespace>.sh`.

Each command sets `lookbackMs` at **runtime**:

```js
lookbackMs: Date.now() - Date.parse("<burst start UTC>")
```

so the customer can run the pack later without editing timestamps. The stream still
opens at the estimated burst start (plus the lookback margin). `runMs` and `idleMs`
decide when it stops.

Replace `USER`, `PASSWORD`, and `HOST` before running. Do not collect the filled-in
connection string with the results.

### How burst start is chosen

1. Collect every warning for the namespace that has a `sourceTime`.
2. Sort those times.
3. Start a new window when the gap to the previous source time is greater than
   `--window-gap-minutes` (default **30**).
4. Open the change stream `--lookback-margin-minutes` (default **5**) **before** the
   first source time in that window, floored to the minute.

The margin exists because source time is approximate. Opening a few minutes early
avoids missing the start of the burst.

### Generated `MONITOR_ARGS`

These values are written into every script. Only `namespaces`, `lookbackMs`,
`appliers`, and `outputFile` vary.

| Parameter | Value | Why |
| --- | --- | --- |
| `namespaces` | One namespace | Isolates that collection’s events so a busy neighbor cannot dominate the sample or hit the unique-doc cap first. |
| `lookbackMs` | `Date.now() - Date.parse(burstStart)` | Replay from the estimated source window, not “the last N minutes of live traffic.” |
| `runMs` | `1800000` (30 minutes) | Drain cap if the stream never goes idle. Long enough for a typical batch job; short enough to fail closed. |
| `idleMs` | `2000` | Stop about two seconds after events stop. The interesting work is the historical burst, not waiting for new writes. |
| `appliers` | Live CEA processor count, or `--appliers` | Matches mongosync’s hash spread (`spread ≈ f * sqrt(N-1)`). Taken from `ceaMemoryUsage.dispatcherToProcessorChannels.numProcessors`, **not** from `recentCRUDStatistics.totalAppliers` on the warning (that field is aggregated and can over-count). If the logs have no `numProcessors`, default **256**. |
| `spreadDisparityThreshold` | `5` | Looser than mongosync’s warning threshold (`> 10`) so the historical window is still flagged if it was skewed but not identical to the 10s warning sample. |
| `minDocCps` | `1` | Per-document rate gate. The JS script requires a value greater than 0. `1` keeps low-rate but highly skewed docs visible. |
| `minTotalCps` | `0` | Do not drop the collection because the **whole** window is quiet. A short historical burst can have a low average rate after lookback. |
| `topDocCountForProxy` | `5` | Print a few busiest `_id`s even when they fail the hot-doc gates (useful when unique/event is ~1.0). |
| `maxUniqueDocs` | `2000000` | Tracking cap for distinct `_id`s. Bulk insert/delete windows can exceed the JS default (200000) and truncate before the burst is understood. |
| `outputFormat` | `"json"` | Machine-readable result for the customer to return. |
| `outputFile` | `hot-doc-spread-check-<ns>-<tag>.json` | One file per mongosh call; tag is the lookback start (`YYYYMMDDTHHMMZ`). |

### Flags that change generated scripts

| Flag | Default | Effect |
| --- | --- | --- |
| `--write-scripts DIR` | off | Write the pack into `DIR` |
| `--appliers N` | `numProcessors`, else `256` | Override `appliers` in every script |
| `--lookback-margin-minutes` | `5` | Minutes before the first source write |
| `--window-gap-minutes` | `30` | Source-time gap that starts a new `mongosh` call |
| `--script-js PATH` | parent `hot-doc-spread-check.js` | JS file copied into the pack |

`--json` and `--write-scripts` can be used together: JSON goes to stdout, scripts
go to `DIR`.

## Interpreting results

After the customer returns the JSON files, start with:

* **unique/event near 1.0** — many distinct `_id`s hashed onto few appliers. Look at
  `_id` type and distribution (monotonic fields, low-cardinality prefixes, hashed
  routing), not a single hot document.
* **unique/event much less than 1.0** — repeated `_id`s. The top documents in the
  hot-doc-spread-check output are the better lead.
* **No events** — the source likely no longer has that oplog range, the lookback
  start is wrong, or the namespace filter does not match.

Mongosync hashes most collections by document `_id`. Capped collections use a
collection-level hash, so every event for that collection maps to one applier and
can look “low parallelization” without a hot `_id`.

## Limitations

* Lag is whatever mongosync last logged. If progress lines are sparse, `lagAgeSeconds`
  in the JSON shows how stale that sample was.
* Source time is not an event timestamp. Do not treat it as exact to the second.
* `--write-scripts` skips a namespace that has warnings but no recoverable
  `sourceTime` (no lag seen yet).
* Generated scripts only help if the source still retains the change-stream history
  for that lookback.

### License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)

DISCLAIMER
----------
Please note: all tools/ scripts in this repo are released for use "AS IS" **without any warranties of any kind**,
including, but not limited to their installation, use, or performance.  We disclaim any and all warranties, either 
express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness 
for a particular purpose.  We do not warrant that the technology will meet your requirements, that the operation 
thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is **at your own risk**.  There is no guarantee that they have been through 
thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with 
their use.

You are responsible for reviewing and testing any scripts you run *thoroughly* before use in any non-testing 
environment.

Thanks,  
The MongoDB Support Team
