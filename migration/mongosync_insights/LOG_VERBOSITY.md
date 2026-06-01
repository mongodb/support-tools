# Log Verbosity and Plot Coverage

Mongosync Insights reads the structured JSON log lines that mongosync writes to its log files. The amount of data available to plot depends directly on the **verbosity level** used when mongosync was running.

## Verbosity Hierarchy

Mongosync uses a cumulative verbosity system. Each level includes all levels below it:

| Level | Severity order | How to enable |
|-------|---------------|---------------|
| `error` | lowest verbosity | Always present |
| `warn`  | ↑ | Always present |
| `info`  | ↑ | Default — no flags needed |
| `debug` | ↑ | `--verbosity 1` |
| `trace` | highest verbosity | `--verbosity 2` |

To set verbosity when starting mongosync:

```bash
# default (info and above)
mongosync --cluster0 "..." --cluster1 "..."

# enable debug logs
mongosync --cluster0 "..." --cluster1 "..." --verbosity 1

# enable trace logs
mongosync --cluster0 "..." --cluster1 "..." --verbosity 2
```

## Effect on Plots and Features

The table below lists every chart and panel in Mongosync Insights, the minimum verbosity required, and the exact log pattern that feeds it.

### Global Migration Metrics

| Chart / Feature | Min. verbosity | Source log pattern |
|----------------|---------------|--------------------|
| Mongosync Phases (scatter + table) | `info` (default) | `"Starting ... phase"` \| `"Commit handler called"` |
| Lag Time (seconds) | `info` (default) | `"Replication progress"` → `lagTimeSeconds` |
| Est. Source Oplog Time Remaining | `info` (default) | `"Replication progress"` → `estimatedOplogTimeRemaining` |
| Ping Latency — src & dst | `info` (default) | `"Operation duration stats"` → `sourcePingLatencyMs` / `destinationPingLatencyMs` |
| Average Source CRUD Event Rate | `info` (default) | `"Average Source CRUD events rate"` → `srcCRUDEventsPerSec` |

> **Note:** `Average Source CRUD events rate` is only emitted by **standalone mongosync**. It is not logged during Live Import runs.

### Collection Copy Metrics

| Chart / Feature | Min. verbosity | Source log pattern |
|----------------|---------------|--------------------|
| Partition Init Progress (time series) | `info` (default) | `"Creating a single/initial partition for..."` |
| Partition Init Summary — doc count & sampler | `info` (default) | `"Pre-sampling information"` |
| Partition Init Summary — **partition count & duration** | **`debug` (`--verbosity 1`)** | `"Persisted a new partition after sampling"` |
| Data Copied Over Time | `info` (default) | `"sent response"` → `body.progress.collectionCopy.estimatedCopiedBytes` |
| Estimated Total & Copied (bar) | `info` (default) | `"sent response"` → `body.progress.collectionCopy` |
| Partitions Copied (time series + bar) | `info` (default) | `"Completed writing X / Y partitions to destination cluster"` |

### CEA Metrics

| Chart / Feature | Min. verbosity | Source log pattern |
|----------------|---------------|--------------------|
| Change Events Applied | `info` (default) | `"Replication progress"` → `totalEventsApplied` |
| Events Rate per Second | `info` (default) | `"Replication progress"` → `eventApplicationRatePerSecond` |
| CEA Source Read — avg / max / ops | `info` (default) | `"Operation duration stats"` → `CEASourceRead` |
| CEA Destination Write — avg / max / ops | `info` (default) | `"Operation duration stats"` → `CEADestinationWrite` |

### Indexes Metrics

| Chart / Feature | Min. verbosity | Source log pattern |
|----------------|---------------|--------------------|
| Index Built Over Time | `info` (default) | `"sent response"` → `body.progress.indexBuilding.indexesBuilt` |
| Total and Index Built (bar) | `info` (default) | `"sent response"` → `body.progress.indexBuilding.totalIndexesToBuild` |

### Verifier Metrics

| Chart / Feature | Min. verbosity | Source log pattern |
|----------------|---------------|--------------------|
| Source Verifier Lag Time | `warn` (automatic) | Field `verifierSrcLagTimeSeconds` present |
| Destination Verifier Lag Time | `warn` (automatic) | Field `verifierDstLagTimeSeconds` present |

> **Note:** Verifier lag lines are emitted by mongosync at `warn` level independently of the `--verbosity` flag. No extra configuration is needed — they appear automatically whenever the live verifier is active.

### Info Tabs (non-chart panels)

| Panel | Min. verbosity | Source log pattern |
|-------|---------------|--------------------|
| Version Info | `info` (default) | `"Version info"` |
| Start Options | `info` (default) | `"Received request"` filtered by `uri=/api/v1/start` |
| Mongosync Options | `info` (default) | `"Mongosync Options"` |
| Hidden Flags | `info` (default) | `"Mongosync HiddenFlags"` |
| Natural Order Collections | `info` (default) | `reason` field → `"Selected for natural order collection reads"` |

> **Note:** Version Info, Mongosync Options, and Hidden Flags are startup log lines. If you upload a **rotated or partial log file** that was captured mid-migration (i.e., after mongosync already rotated its initial log), these panels will be empty. The data is present in the earlier rotated log files, not the current one.

## Summary

| Verbosity | Charts and panels available |
|-----------|----------------------------|
| Default (`info`, no flags) | Everything **except** Partition Init partition count & duration columns |
| `--verbosity 1` (`debug`) | Full coverage, including Partition Init partition count & duration |
| `--verbosity 2` (`trace`) | No additional plots currently — `trace`-level lines are not yet extracted by Mongosync Insights |

## Recommendation

For a complete analysis, capture mongosync logs with at least `--verbosity 1`. This adds one additional log line per partition created (`"Persisted a new partition after sampling"`), which is low volume and has negligible performance impact. All other charts work at the default verbosity level.
