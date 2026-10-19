# Hot Doc Spread Check

## Purpose

`hot-doc-spread-check.js` is a mongosh script that scans recent change activity and identifies documents that are hot enough to plausibly explain high applier skew.

In this script, a document is considered a hot-doc candidate only if it passes all three gates:

* spread-disparity gate
* per-document changes-per-second gate
* total-window changes-per-second gate

The report also analyzes short event-time windows (10 seconds by default) to find bursts that whole-lookback averages can dilute. Burst candidates use the same three gates within a complete short window. This estimates per-document concentration; it does not reproduce mongosync's actual per-applier routing or spread metric.

## Setup

No npm installation or third-party modules are required. Run the script directly with mongosh. It uses mongosh's built-in BSON helpers and the built-in `fs` module to write reports.

Optional regression tests use only Node.js built-ins (Node.js 18 or newer):

```bash
node --test hot-doc-spread-check.test.js
```

To run the optional live test against a deployment you choose:

```bash
HOT_DOC_SPREAD_CHECK_URI="mongodb://localhost:27017" node --test hot-doc-spread-check.test.js
```

The live test watches a test namespace without creating it or writing database data. It checks that a quiet stream remains partial with unavailable CPS. It writes its report to a temporary directory and removes that directory afterward. The test file is not needed to run the script.

## Quick start

### 1. Run with defaults against all user namespaces

Use this when you want a fast first pass over recent write activity across the deployment:

```bash
mongosh "mongodb://user:password@host/admin" \
  --file hot-doc-spread-check.js
```

Defaults:

* 5-minute lookback window
* 128 appliers
* spread disparity threshold 5
* minimum 2 doc changes/sec
* minimum 10 total changes/sec
* top 5 documents included in proxy analysis

### 2. Run against one namespace

Use this when you already know which collection is suspect:

```bash
mongosh "mongodb://user:password@host/admin" \
  --eval 'globalThis.MONITOR_ARGS = { namespaces: ["sdtest5.events"] }' \
  --file hot-doc-spread-check.js
```

### 3. Run with custom tuning

Use this when you want a different proxy depth, a different window, or more conservative thresholds:

```bash
mongosh "mongodb://user:password@host/admin" \
  --eval 'globalThis.MONITOR_ARGS = {
    namespaces: ["sdtest5.events"],
    appliers: 128,
    spreadDisparityThreshold: 5,
    minDocCps: 2,
    minTotalCps: 10,
    topDocCountForProxy: 10,
    lookbackMs: 300000,
    outputFormat: "json"
  }' \
  --file hot-doc-spread-check.js
```

### 4. Analyze an explicit timeframe

Provide both `startTime` and `endTime` as ISO-8601 timestamps with an explicit timezone. The start is inclusive and the end is exclusive. This example analyzes 15:52:00-15:58:30 at UTC+03:00:

```bash
mongosh \
  --eval 'globalThis.MONITOR_ARGS = {
    startTime: "2026-10-19T15:52:00+03:00",
    endTime: "2026-10-19T15:58:30+03:00"
  }' \
  --file hot-doc-spread-check.js
```

The interval must still be available in the deployment's oplog, and the end must not be later than the server watermark. Do not set `lookbackMs` together with explicit times.

### 5. Generate Markdown output

Use this when you want a shareable Markdown report:

```bash
mongosh "mongodb://user:password@host/admin" \
  --eval 'globalThis.MONITOR_ARGS = {
    namespaces: ["sdtest5.events"],
    outputFormat: "markdown"
  }' \
  --file hot-doc-spread-check.js
```

### 6. Generate both JSON and Markdown output

Use this when you want machine-readable and human-readable output in one run:

```bash
mongosh "mongodb://user:password@host/admin" \
  --eval 'globalThis.MONITOR_ARGS = {
    namespaces: ["sdtest5.events"],
    outputFormat: "both"
  }' \
  --file hot-doc-spread-check.js
```

### 7. Read the output quickly

Start with these sections in the console output:

* `TOP-N COMBINED SHARE` to understand concentration among the busiest documents
* `TOP-N DOCUMENTS` to see the documents with the most observed operations
* `HOT DOCUMENTS` for whole-window candidates when the sample is complete
* `PEAK DOCUMENT BURSTS` for the top documents' busiest complete short windows
* `BURST CANDIDATES` for documents that passed all gates in at least one complete window

## Example output

### Default parameters

This default-lookback run is partial because the stream did not reach its caught-up watermark. Whole-window CPS and hot-document qualification are unavailable, but completed 10-second burst windows can still produce candidates:

```text
mongosh --file hot-doc-spread-check.js

Reading change stream for ALL namespaces from 2026-10-19T12:53:33.000Z (lookback interval: current=5m, default=5m) ...
Sample endpoint (exclusive): 2026-10-19T12:58:33.000Z

Stream closed. Reason: idle-timeout. Matched events: 71577. Qualified doc events: 71577.
Wrote JSON results to hot-doc-spread-check.json

================================================================================================================
TOP-5 COMBINED SHARE
================================================================================================================
Appliers: 128  SpreadDisparityThreshold: 5  RequiredShare(single-doc): 44.37%
MinDocCps: 2  MinTotalCps: 10 (Cps means changes per second)
Burst window: 10s  Complete event windows analyzed: 29
Unique docs tracked: 5 / 200000
Qualified changes in window: 71577  Total changes/sec: N/A
Top-5 combined ops   : 71577
Top-5 combined share : 100.00%
Top-5 single-doc spread equivalent : 11.269
Sample completeness: partial  Rate window seconds: N/A  Reading duration seconds: 5.533
Analysis status: inconclusive
WARNING: Incomplete analysis: the stream did not reach the caught-up watermark. Hot documents may have been missed.
WARNING: Workload CPS and CPS gates were not evaluated for this partial sample. Counts and shares describe only the observed activity.
WARNING: Burst results include only event-time windows known to be complete; the trailing incomplete window is excluded.
WARNING: A quiet or filtered stream may already have been fully read, but completion cannot be confirmed without a matching event at the sample endpoint.

================================================================================================================
TOP-5 DOCUMENTS (BY OP COUNT) (Partial Sample)
================================================================================================================
rank  opCount  insert  delete  update   share%  spreadDisp   docCps  totalCps  namespace               _id
  1    32085       1       0   32084    44.83       5.052      N/A       N/A  sdtest5.events          "hot-doc-1"
  2    32085       1       0   32084    44.83       5.052      N/A       N/A  sdtest5.events          "hot-doc-2"
  3     2469       1       0    2468     3.45       0.389      N/A       N/A  sdtest5.events          "hot-doc-3"
  4     2469       1       0    2468     3.45       0.389      N/A       N/A  sdtest5.events          "hot-doc-4"
  5     2469       1       0    2468     3.45       0.389      N/A       N/A  sdtest5.events          "hot-doc-5"

================================================================================================================
HOT DOCUMENTS (Partial Sample)
================================================================================================================
Hot-document qualification was not evaluated: workload CPS is unavailable for this partial sample. Inspect the top documents for observed counts and shares.
rank  opCount  insert  delete  update   share%  spreadDisp   docCps  totalCps  namespace               _id

================================================================================================================
PEAK DOCUMENT BURSTS (10s WINDOWS)
================================================================================================================
rank  window start              opCount  share%  spreadDisp   docCps  totalCps  namespace               _id
  1  2026-10-19T12:58:13.000Z     1106   44.85       5.054  110.600   246.600  sdtest5.events          "hot-doc-1"
  2  2026-10-19T12:54:33.000Z     1105   44.83       5.052  110.500   246.500  sdtest5.events          "hot-doc-2"
  3  2026-10-19T12:54:33.000Z       85    3.45       0.389    8.500   246.500  sdtest5.events          "hot-doc-3"
  4  2026-10-19T12:54:33.000Z       85    3.45       0.389    8.500   246.500  sdtest5.events          "hot-doc-4"
  5  2026-10-19T12:54:33.000Z       85    3.45       0.389    8.500   246.500  sdtest5.events          "hot-doc-5"

BURST CANDIDATES (PASSED ALL GATES)
rank  window start              opCount  share%  spreadDisp   docCps  totalCps  namespace               _id
  1  2026-10-19T12:58:13.000Z     1106   44.85       5.054  110.600   246.600  sdtest5.events          "hot-doc-1"
  2  2026-10-19T12:54:33.000Z     1105   44.83       5.052  110.500   246.500  sdtest5.events          "hot-doc-2"
```

### Explicit timeframe

This example analyzes the interval from 15:52:00 to 15:58:30 at UTC+03:00. The transcript displays the converted UTC interval and a complete result:

```text
mongosh --eval 'globalThis.MONITOR_ARGS = {
  startTime: "2026-10-19T15:52:00+03:00",
  endTime: "2026-10-19T15:58:30+03:00"
}' --file hot-doc-spread-check.js
{
  startTime: '2026-10-19T15:52:00+03:00',
  endTime: '2026-10-19T15:58:30+03:00'
}

Reading change stream for ALL namespaces from 2026-10-19T12:52:00.000Z (requested interval) ...
Sample endpoint (exclusive): 2026-10-19T12:58:30.000Z

Stream closed. Reason: caught-up. Matched events: 71838. Qualified doc events: 71838.
Wrote JSON results to hot-doc-spread-check.json

================================================================================================================
TOP-5 COMBINED SHARE
================================================================================================================
Appliers: 128  SpreadDisparityThreshold: 5  RequiredShare(single-doc): 44.37%
MinDocCps: 2  MinTotalCps: 10 (Cps means changes per second)
Burst window: 10s  Complete event windows analyzed: 30
Unique docs tracked: 5 / 200000
Qualified changes in window: 71838  Total changes/sec: 184.200
Top-5 combined ops   : 71838
Top-5 combined share : 100.00%
Top-5 single-doc spread equivalent : 11.269
Sample completeness: complete  Rate window seconds: 390.000  Reading duration seconds: 3.382
Analysis status: complete

================================================================================================================
TOP-5 DOCUMENTS (BY OP COUNT)
================================================================================================================
rank  opCount  insert  delete  update   share%  spreadDisp   docCps  totalCps  namespace               _id
  1    32202       1       0   32201    44.83       5.052   82.569   184.200  sdtest5.events          "hot-doc-1"
  2    32202       1       0   32201    44.83       5.052   82.569   184.200  sdtest5.events          "hot-doc-2"
  3     2478       1       0    2477     3.45       0.389    6.354   184.200  sdtest5.events          "hot-doc-3"
  4     2478       1       0    2477     3.45       0.389    6.354   184.200  sdtest5.events          "hot-doc-4"
  5     2478       1       0    2477     3.45       0.389    6.354   184.200  sdtest5.events          "hot-doc-5"

================================================================================================================
HOT DOCUMENTS
================================================================================================================
2 hot document(s) detected in the sample.
rank  opCount  insert  delete  update   share%  spreadDisp   docCps  totalCps  namespace               _id
  1    32202       1       0   32201    44.83       5.052   82.569   184.200  sdtest5.events          "hot-doc-1"
  2    32202       1       0   32201    44.83       5.052   82.569   184.200  sdtest5.events          "hot-doc-2"

================================================================================================================
PEAK DOCUMENT BURSTS (10s WINDOWS)
================================================================================================================
rank  window start              opCount  share%  spreadDisp   docCps  totalCps  namespace               _id
  1  2026-10-19T12:56:10.000Z     1118   44.83       5.052  111.800   249.400  sdtest5.events          "hot-doc-1"
  2  2026-10-19T12:56:10.000Z     1118   44.83       5.052  111.800   249.400  sdtest5.events          "hot-doc-2"
  3  2026-10-19T12:56:10.000Z       86    3.45       0.389    8.600   249.400  sdtest5.events          "hot-doc-3"
  4  2026-10-19T12:56:10.000Z       86    3.45       0.389    8.600   249.400  sdtest5.events          "hot-doc-4"
  5  2026-10-19T12:56:10.000Z       86    3.45       0.389    8.600   249.400  sdtest5.events          "hot-doc-5"

BURST CANDIDATES (PASSED ALL GATES)
rank  window start              opCount  share%  spreadDisp   docCps  totalCps  namespace               _id
  1  2026-10-19T12:56:10.000Z     1118   44.83       5.052  111.800   249.400  sdtest5.events          "hot-doc-1"
  2  2026-10-19T12:56:10.000Z     1118   44.83       5.052  111.800   249.400  sdtest5.events          "hot-doc-2"
```

The spread-disparity part is based on the internal hot-doc detection proposal, which models the single-hot-document case as:

$$
\text{SpreadDisparity} \approx f \cdot \sqrt{N-1}
$$

where:

* \(N\) = number of appliers
* \(f\) = fraction of all events in the observed window that belong to one document

For a detection threshold of 5, the corresponding per-document share threshold is:

$$
f \ge \frac{5}{\sqrt{N-1}}
$$

For \(N=128\), that is about **44.4%** of all events in the window.

## What the script counts

The script watches change-stream events and counts only these operation types:

* `insert`
* `update`
* `replace` (counted as `update`)
* `delete`

For each document, it tracks:

* total operation count
* insert count
* update count
* delete count

## Current default settings

These are the current defaults used by the script in this README. `startTime` and `endTime` are optional; when both are provided they select an explicit historical interval instead of `lookbackMs`:

```js
{
  namespaces: [],
  lookbackMs: 5 * 60 * 1000,
  burstWindowMs: 10 * 1000,
  runMs: 5 * 60 * 1000,
  idleMs: 2000,
  maxUniqueDocs: 200000,
  appliers: 128,
  spreadThreshold: 5,
  minDocCps: 2,
  minTotalCps: 10,
  topDocCountForProxy: 5,
  maxBurstCandidates: 100,
  outputFormat: "json",
  outputFile: "hot-doc-spread-check.json"
}
```

Meaning:

* `namespaces: []`
  * watch all namespaces
* `lookbackMs: 5 minutes`
  * sample a fixed interval ending at the whole-second boundary of the server-derived startup watermark
  * interval length is rounded up to whole seconds; `rateWindowSeconds` reports the actual duration when complete
  * must be greater than 0
* `startTime` and `endTime` (optional)
  * ISO-8601 timestamps with explicit timezone offsets, for example `2026-10-19T08:00:00-04:00`
  * provide both to analyze the interval `[startTime, endTime)`; do not also set `lookbackMs`
  * timestamps must have whole-second precision, and the interval must be in the past and available in the oplog
* `burstWindowMs: 10 seconds`
  * duration of each event-time bucket used by burst analysis
  * must be a whole number of seconds and at least 1 second
  * buckets are anchored to the sample start; a shorter final bucket is evaluated using its actual duration
  * if the lookback is shorter than this setting, the effective burst window is shortened to the sample length
* `runMs: 5 minutes`
  * hard maximum runtime
* `idleMs: 2000`
  * stop after 2 seconds without a matching event
  * set to `0` to disable idle-timeout stopping; `runMs` still limits runtime
  * an idle stop is partial, not evidence of completion
* `maxUniqueDocs: 200000`
  * maximum number of unique namespace+_id rows tracked in memory
  * safety cap to prevent unbounded memory growth on high-cardinality workloads
  * when reached, the run stops early with stop reason `max-unique-docs-reached`
* `appliers: 128`
  * used in the spread-disparity math
  * must be an integer greater than or equal to 2
* `spreadThreshold: 5`
  * the spread-disparity activation threshold used by the proposal
  * alias: `spreadDisparityThreshold` (same meaning)
* `minDocCps: 2`
  * a document must average at least 2 changes/sec in the window
* `minTotalCps: 10`
  * the whole window must average at least 10 changes/sec
* `topDocCountForProxy: 5`
  * number of top documents used for combined proxy analysis (integer range 1..100)
* `maxBurstCandidates: 100`
  * maximum number of burst candidate rows shown in console and Markdown output
  * omitted-row count is reported; the JSON report retains the full candidate list
* `outputFormat: "json"`
  * controls report file format
  * valid values: `json`, `markdown`, `both`
  * legacy alias: `outputMarkdown: true` is treated as `outputFormat: "markdown"`
* `outputFile: "hot-doc-spread-check.json"`
  * output path for single-format runs
  * path is used as provided (supports both relative and absolute paths)
  * if `outputFormat: "markdown"` and `outputFile` is left at the default, the script writes `hot-doc-spread-check.md`

## How the script works

### 1. It opens a deployment-level change stream

The script uses a deployment-level watch so it can observe one namespace, several namespaces, or all namespaces, depending on `namespaces`.

Internal namespaces are always excluded from analysis: `admin`, `config`, `local`, and `system.*`.

If `namespaces` is set, each entry must be in:

```text
database.collection
```

format.

If `namespaces` includes an internal namespace (`admin`, `config`, `local`, or `system.*`), the script fails fast with a validation error.

### 2. It replays a time window

The script supports two ways to select the interval. By default, it captures a server-derived timestamp at startup, takes its whole-second boundary as the exclusive endpoint, and starts from:

```text
sampleEndAt - ceil(lookbackMs / 1000) seconds
```

When both `startTime` and `endTime` are provided, those timestamps instead define the interval after conversion to UTC whole seconds. The requested start is inclusive and the end is exclusive. The script counts matching change events in `[sampleStartAt, sampleEndAt)`. Events at or beyond the endpoint confirm progress but are not counted. This excludes the endpoint's second, avoiding an incomplete set of operations sharing the same timestamp. Local client clock skew and replay speed do not change the sampling interval.

The script confirms completion only when a matching event reaches the fixed endpoint. It does not decode opaque resume tokens or assume an empty read means it is caught up. On a quiet or namespace-filtered stream, all available historical writes may have been read without such an event. The run then remains partial when `idleMs` (2 seconds by default) or `runMs` is reached. This conservative limitation keeps the script standalone without presenting unverified rates as complete-window measurements.

This means the script is a **fixed-window sampler**, not a forever-running live monitor. Explicit historical intervals must still be present in the deployment's oplog.

### 3. It filters to document-level write activity

Only `insert`, `update`, `replace`, and `delete` are counted.

Events without a document `_id` are ignored.

Internal namespaces are always ignored: `admin`, `config`, `local`, and `system.*`.

### 4. It aggregates counts per document

For every namespace and `_id`, the script builds a row like:

```js
{
  ns,
  docId,
  opCount,
  insert,
  update,
  delete
}
```

### 5. It computes window-wide totals

After the stream closes, the script computes:

* `qualifiedEventsSeen`
  * all counted document-level write events in the window
* `totalChangesPerSec`
  * `qualifiedEventsSeen / rateWindowSeconds` for a confirmed complete interval
  * `null` for a partial run; replay duration is never used as a workload-rate denominator

### Short-window burst analysis

The separate `burstAnalysis` result evaluates each fully observed event-time bucket. For a document in a bucket it computes:

```text
eventShare = document operations in bucket / all operations in bucket
spreadDisparityEstimate = eventShare * sqrt(appliers - 1)
docChangesPerSec = document operations in bucket / bucket duration
totalChangesPerSec = all operations in bucket / bucket duration
```

It applies the same spread, minimum document CPS, and minimum total CPS gates independently within each bucket. A document appears in `burstAnalysis.hotDocuments` if it passes all three gates in at least one complete bucket. `topDocuments` reports each document's busiest complete bucket, including its start time, counts, share, estimated disparity, and rates. A short burst can therefore qualify here even if the document fails the whole-lookback CPS gate.

Buckets are aligned to `sampleStartAt`. Change-stream timestamps have one-second resolution, so this analysis does not resolve sub-second bursts. The spread value remains a per-document estimate; it does not inspect actual mongosync applier assignments and is not equivalent to mongosync's `mongosync_cea_spread_disparity` metric.

For a partial overall sample, only buckets known to have ended are evaluated. The active trailing bucket is excluded rather than treated as a completed interval. If no bucket ended before the run stopped, `completeWindowsAnalyzed` is zero and no burst candidates are reported. This avoids inflating CPS by dividing partial-bucket counts by replay time.

### 6. It computes the per-document hotness metrics

For each document, it computes:

```text
eventShare = docChanges / allChangesInWindow
spreadDisparityEstimate = eventShare * sqrt(appliers - 1)
docChangesPerSec = docChanges / windowSeconds
```

The spread formula and the threshold logic come directly from the internal proposal’s single-hot-document derivation.

### 7. It applies three gates

A document is returned in `hotDocuments` only if all three are true:

```text
spreadDisparityEstimate >= spreadDisparityThreshold
docChangesPerSec >= minDocCps
totalChangesPerSec >= minTotalCps
```

For partial runs, whole-lookback CPS fields, both whole-lookback CPS gate results, and `qualifies` are `null` (not evaluated). `hotDocuments` is empty because full-window qualification is unavailable, not because all documents passed or failed. Counts, shares, and spread estimates remain available for the top documents, explicitly labeled partial. `burstAnalysis` may still report candidates from earlier event-time windows that were fully observed before the run stopped.

## Why the script uses the two extra CPS gates

The proposal explicitly notes that a pure spread-disparity check should also be gated by an events-per-second style threshold to avoid false positives during slow periods.

The two extra checks serve different purposes:

### `docChangesPerSec >= minDocCps`

This prevents a document from looking “hot” only because the sample window is tiny or quiet.

Example: if one doc gets 2 out of 3 events, its share is large, but that does not necessarily make it operationally important.

### `totalChangesPerSec >= minTotalCps`

This prevents the whole sample window from being treated as meaningful when overall traffic is too low.

This is effectively a sample-quality / throughput floor.

## What the script is good at detecting

This script is best understood as a **single-document detector**.

It works well when:

* one document dominates the window
* or multiple documents each independently dominate enough to cross the single-doc threshold

For example, with \(N=128\) and threshold 5, a document needs about **44.4%** of all window events to pass individually.

That also means the maximum number of documents that can each pass individually is limited by total share. For \(N=128\), at most **2** documents can each be above the threshold at the same time, because 3 documents at ~44.4% each would require more than 100% total traffic.

## Important limitation

The spread-disparity math used here is derived under these assumptions:

* non-hot documents are spread evenly across appliers
* exactly 1 hot document exists
* the hot document has a stable rate over the measurement window

So this script may under-detect **multi-hot** cases where:

* no single document reaches the threshold
* but 2 or 3 documents together create the skew

That is a limitation of the underlying approximation, not a bug in the script.

## Stop conditions

The script stops when any of these happens:

* `caught-up`
  * a matching event reached the fixed exclusive endpoint
* `idle-timeout`
  * `idleMs` elapsed without a matching event; 2 seconds by default, disabled when set to `0`
* `run-ms-exceeded`
  * hard max runtime reached before completion could be confirmed
* `max-unique-docs-reached`
  * reached `maxUniqueDocs` safety cap for unique namespace+_id rows

## Output

The script writes report files according to `outputFormat` (`json`, `markdown`, or `both`) and also prints a console summary.

Note: the `json` output file is emitted as strict MongoDB Extended JSON (EJSON). If you are consuming the file programmatically, prefer `EJSON.parse()`.

If the run stops before `caught-up`, the sample is marked partial. `rateWindowSeconds`, `docChangesPerSec`, and `totalChangesPerSec` are `null` in JSON and shown as `N/A` in console and Markdown. `observedWindowSeconds` reports reading duration only; it is never used to calculate workload CPS.

Partial runs have `analysisStatus: "inconclusive"` and `ratesAvailable: false` for whole-lookback rates. Console, JSON, and Markdown reports include warnings and state that whole-lookback hot-document qualification was not evaluated. Top-document counts and shares describe only the observed activity and cannot rule out hotspots elsewhere in the interval. Separately, `burstAnalysis` can include results for fully observed event-time buckets, but excludes the unfinished trailing bucket. A `complete` status means the fixed interval was consumed, not that all possible hotspots have been ruled out.

Compatibility note: consumers that previously assumed numeric CPS fields or boolean gate results must now handle `null` for partial samples. Check `ratesAvailable` before using CPS values or interpreting `hotDocuments`.

When `maxUniqueDocs` documents have been tracked, events for already-tracked documents can still be counted. The next unseen document stops the run. A capped run therefore covers only a chronological prefix of the activity, not a representative sample of the whole window. Its reports warn:

> Incomplete analysis: maxUniqueDocs reached. Later activity was not analyzed, so hot documents may have been missed. Rerun with fewer namespaces or increase maxUniqueDocs if memory permits.

The cap remains a memory-safety limit. Narrow the requested namespaces or raise `maxUniqueDocs` only if memory permits, then rerun to obtain a complete sample.

### JSON output

Top-level fields include:

* `generatedAt`
* `namespacesRequested`
* `timeRangeMode` (`lookback` or `explicit`)
* `lookbackMs` (duration of the analyzed interval, including when explicit timestamps were used)
* `burstWindowMs` (effective burst-window duration)
* `appliers`
* `spreadDisparityThreshold`
* `spreadThreshold` (legacy alias)
* `minShareRequired`
* `minDocCps`
* `minTotalCps`
* `maxUniqueDocs`
* `matchedEventsSeen`
* `qualifiedEventsSeen`
* `uniqueDocsTracked`
* `sampleIsPartial`
* `ratesAvailable` (false for partial samples)
* `sampleStartAt` (inclusive server-time BSON timestamp)
* `sampleEndAt` (exclusive server-time BSON timestamp)
* `analysisStatus` (`complete` when caught up; otherwise `inconclusive`)
* `warnings` (an array of warning strings; empty for complete samples)
* `hotDocumentsSummary` (a result message explicitly identifying partial samples)
* `burstAnalysis`
  * `windowMs`
  * `completeWindowsAnalyzed` (non-empty event-time buckets known to have ended)
  * `summary` (count of distinct documents that passed all burst gates in at least one complete bucket)
  * `candidateDisplayLimit`, `candidateRowsDisplayed`, and `candidateRowsOmitted` (human-readable output cap and counts)
  * `topDocuments` (documents ranked by peak complete-bucket CPS)
  * `hotDocuments` (full JSON list of documents that passed all three gates in at least one complete bucket)
* `rateWindowSeconds` (actual complete interval duration; otherwise `null`)
* `observedWindowSeconds` (reading duration, not a workload-rate window)
* `totalChangesPerSec` (`null` when partial)
* `stopReason`
* `cappedByMaxUniqueDocs`
* `lastClusterTime`
* `hotDocuments`
* `topCombined`
  * `requestedDocCount`
  * `effectiveDocCount`
  * `opCount`
  * `share`
  * `singleDocSpreadEquivalent`
  * `documents`

When `outputFormat` is:

* `json`
  * writes strict EJSON output to `outputFile` (default: `hot-doc-spread-check.json`)
  * CPS fields use the fixed interval duration only when the run reaches `caught-up`; otherwise they are `null` and `sampleIsPartial` is `true`
* `markdown`
  * writes Markdown output to `outputFile` or `hot-doc-spread-check.md` when default outputFile is unchanged
* `both`
  * writes strict EJSON to `hot-doc-spread-check.json` and Markdown to `hot-doc-spread-check.md`

Each `hotDocuments` entry includes:

```js
{
  ns,
  docId,
  docChanges,
  opCount,
  insert,
  update,
  delete,
  peakBurstWindow,
  qualifyingBurstWindow,
  eventShare,
  spreadDisparityEstimate,
  docChangesPerSec,
  totalChangesPerSec,
  passesSpreadGate,
  passesDocCpsGate,
  passesTotalCpsGate,
  qualifies
}
```

### Console output

The console output prints:

* overall window stats
* threshold values
* sample completeness and the rate-window duration used for CPS calculations
* analysis status and warnings for incomplete samples
* top-N combined share and single-doc spread equivalent
* top-N documents (same columns as hot-doc output)
* hot documents that passed all gates
* peak document bursts in complete short windows, limited to `topDocCountForProxy` documents and ranked by peak-window CPS
* up to `maxBurstCandidates` burst candidates that passed all gates, with one qualifying window per document; an omitted-row count is printed when needed. JSON retains the full list.

## How to run it

### Run against all namespaces

```bash
mongosh "mongodb://user:password@host/admin" \
  --file hot-doc-spread-check.js
```

### Run against selected namespaces

```bash
mongosh "mongodb://user:password@host/admin" \
  --eval 'globalThis.MONITOR_ARGS = { namespaces: ["sdtest5.events"] }' \
  --file hot-doc-spread-check.js
```

### Override thresholds

```bash
mongosh "mongodb://user:password@host/admin" \
  --eval 'globalThis.MONITOR_ARGS = {
    namespaces: ["sdtest5.events"],
    appliers: 128,
    spreadDisparityThreshold: 5,
    minDocCps: 2,
    minTotalCps: 10,
    topDocCountForProxy: 10,
    lookbackMs: 300000,
    outputFormat: "json"
  }' \
  --file hot-doc-spread-check.js
```

## How to read the results

### If `hotDocuments` is empty

Possible reasons:

* no document crossed the spread threshold
* a document crossed the spread threshold but failed `minDocCps`
* the whole sample window failed `minTotalCps`
* the workload was multi-hot but no single document individually crossed the single-doc threshold

### If 1 document appears

That is the cleanest “single hot document” case.

### If 2 documents appear

That means both documents independently passed the single-doc gate.

For \(N=128\), that is possible only if both are each near or above ~44.4% of all events in the window.

## Practical tuning guidance

### More sensitive / investigation mode

Good for debugging and lab work:

```js
minDocCps: 2,
minTotalCps: 10
```

### More conservative / production screening

Good for reducing false positives:

```js
minDocCps: 5,
minTotalCps: 20
```

### Very permissive / test mode

Good for synthetic testing:

```js
minDocCps: 1,
minTotalCps: 0
```

## Summary

This script is a focused detector for documents that are individually hot enough to explain high spread disparity in a recent window.

Its decision rule is:

* high enough share of all window events
* high enough per-document throughput
* high enough total-window throughput

That makes it simple, explainable, and practical for identifying strong single-document hotspot candidates.


---

## Sources

- [EP: Automatically detect and mitigate hot docs](https://docs.google.com/document/d/1mHBMjpeYnQKJyxAWjhUL7OBhGJ2733uakUWZZCsp5p4)

### License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)

DISCLAIMER
----------
Please note: all tools/ scripts in this repo are released for use "AS IS" **without any warranties of any kind**,
including, but not limited to their installation, use, or performance. We disclaim any and all warranties, either 
express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness 
for a particular purpose. We do not warrant that the technology will meet your requirements, that the operation 
thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is **at your own risk**. There is no guarantee that they have been through 
thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with 
their use.

You are responsible for reviewing and testing any scripts you run *thoroughly* before use in any non-testing 
environment.

Thanks,  
The MongoDB Support Team
