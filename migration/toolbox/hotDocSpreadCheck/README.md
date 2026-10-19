# Hot Doc Spread Check

## Purpose

`hot-doc-spread-check.js` is a mongosh script that scans recent change activity and identifies documents that are hot enough to plausibly explain high applier skew.

In this script, a document is considered a hot-doc candidate only if it passes all three gates:

* spread-disparity gate
* per-document changes-per-second gate
* total-window changes-per-second gate

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

### 4. Generate Markdown output

Use this when you want a shareable Markdown report:

```bash
mongosh "mongodb://user:password@host/admin" \
  --eval 'globalThis.MONITOR_ARGS = {
    namespaces: ["sdtest5.events"],
    outputFormat: "markdown"
  }' \
  --file hot-doc-spread-check.js
```

### 5. Generate both JSON and Markdown output

Use this when you want machine-readable and human-readable output in one run:

```bash
mongosh "mongodb://user:password@host/admin" \
  --eval 'globalThis.MONITOR_ARGS = {
    namespaces: ["sdtest5.events"],
    outputFormat: "both"
  }' \
  --file hot-doc-spread-check.js
```

### 6. Read the output quickly

Start with these sections in the console output:

* `TOP-N COMBINED SHARE` to understand how much of the window is concentrated in the busiest documents
* `TOP-N DOCUMENTS` to see which documents dominate the sample even if they do not pass the hot-doc gates
* `HOT DOCUMENTS` to see which documents passed all thresholds

## Example output

The following example shows what a successful run can look like:

```bash
mongosh "mongodb+srv://user:password@cluster0.name.mongodb.net/" --file hot-doc-spread-check.js
Reading change stream for ALL namespaces from 2026-07-22T13:17:50.000Z ...
Stream closed. Reason: idle-timeout. Matched events: 20595. Qualified doc events: 20595.
Wrote JSON results to hot-doc-spread-check.json

================================================================================================================
TOP-5 COMBINED SHARE
================================================================================================================
Appliers: 128  SpreadDisparityThreshold: 5  RequiredShare(single-doc): 44.37%
MinDocCps: 2  MinTotalCps: 10
CPS means changes per second.
Qualified changes in window: 20595  Total changes/sec: 68.650
Top-5 combined ops   : 20595
Top-5 combined share : 100.00%
Top-5 single-doc spread equivalent : 11.269

================================================================================================================
TOP-5 DOCUMENTS (BY OP COUNT)
================================================================================================================
rank  opCount   insert  delete  update   share%   spreadDisp   docCps   totalCps   namespace               _id
  1     9231       1       0    9230    44.82       5.051   30.770    68.650   sdtest5.events          "hot-doc-1"
  2     9231       1       0    9230    44.82       5.051   30.770    68.650   sdtest5.events          "hot-doc-2"
  3      711       1       0     710     3.45       0.389    2.370    68.650   sdtest5.events          "hot-doc-3"
  4      711       1       0     710     3.45       0.389    2.370    68.650   sdtest5.events          "hot-doc-4"
  5      711       1       0     710     3.45       0.389    2.370    68.650   sdtest5.events          "hot-doc-5"

================================================================================================================
HOT DOCUMENTS
================================================================================================================
rank  opCount   insert  delete  update   share%   spreadDisp   docCps   totalCps   namespace               _id
  1     9231       1       0    9230    44.82       5.051   30.770    68.650   sdtest5.events          "hot-doc-1"
  2     9231       1       0    9230    44.82       5.051   30.770    68.650   sdtest5.events          "hot-doc-2"
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

These are the current defaults used by the script in this README:

```js
{
  namespaces: [],
  lookbackMs: 5 * 60 * 1000,
  runMs: 5 * 60 * 1000,
  idleMs: 2000,
  maxUniqueDocs: 200000,
  appliers: 128,
  spreadThreshold: 5,
  minDocCps: 2,
  minTotalCps: 10,
  topDocCountForProxy: 5,
  outputFormat: "json",
  outputFile: "hot-doc-spread-check.json"
}
```

Meaning:

* `namespaces: []`
  * watch all namespaces
* `lookbackMs: 5 minutes`
  * start reading from 5 minutes in the past
  * must be greater than 0
* `runMs: 5 minutes`
  * hard maximum runtime
* `idleMs: 2000`
  * stop after 2 seconds of inactivity once events have started
  * set to `0` to disable idle-timeout stopping
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

### 2. It replays a recent time window

The script starts from:

```text
now - lookbackMs
```

and replays matching change events from that point forward.

This means the script is primarily a **recent-window sampler**, not a forever-running live monitor.

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
  * `qualifiedEventsSeen / windowSeconds`

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
  * it observed a matching event with `clusterTime` at or beyond the server-derived logical-time watermark captured when the stream was opened
* `idle-timeout`
  * no matching events arrive for `idleMs` after activity has started
* `run-ms-exceeded`
  * hard max runtime reached (this can occur on quiet workloads where no matching event is observed at or beyond the open-time watermark)
* `max-unique-docs-reached`
  * reached `maxUniqueDocs` safety cap for unique namespace+_id rows

## Output

The script writes report files according to `outputFormat` (`json`, `markdown`, or `both`) and also prints a console summary.

Note: the `json` output file is emitted as strict MongoDB Extended JSON (EJSON). If you are consuming the file programmatically, prefer `EJSON.parse()`.

If the run stops before `caught-up`, the sample is marked partial and rate-based fields use the elapsed wall-clock time from stream open to stop time rather than the full `lookbackMs` window.

### JSON output

Top-level fields include:

* `generatedAt`
* `namespacesRequested`
* `lookbackMs`
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
* `rateWindowSeconds`
* `observedWindowSeconds`
* `totalChangesPerSec`
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
  * CPS fields use `lookbackMs` only when the run reaches `caught-up`; otherwise they use the elapsed wall-clock time from stream open to stop time and `sampleIsPartial` is `true`
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
* top-N combined share and single-doc spread equivalent
* top-N documents (same columns as hot-doc output)
* hot documents that passed all gates

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

## Related: estimate source time from mongosync warnings

When mongosync has already logged CEA low-parallelization warnings, use
[`ceaLowParallelizationSourceTimes`](./ceaLowParallelizationSourceTimes/README.md)
to map those warnings back to approximate source write times and to generate
one-namespace `hot-doc-spread-check.js` scripts for those windows.

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
