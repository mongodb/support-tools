## Usage 

python3 report_ftdc_with_wt_metrics.py /Users/adhiyan.chattopadhyay/Downloads/d\ 2/d1/optimus/dev/data/diagnostic.data 

## Sample Report 
#### JSON Metrics Timeframe Report

### Summary

| Metric | Value |
| --- | --- |
| Complete snapshots parsed | 89740 |
| Start timestamp | 2026-08-12T03:10:48.003000Z |
| End timestamp | 2026-08-13T05:37:53.003000Z |
| Elapsed time | 26h 27m 5.000s |
| Average sample interval | 1.061s |

### Operation counts at start and end

| Counter | Start | End | Delta |
| --- | ---: | ---: | ---: |
| insert | 889338 | 2858002 | 1968664 |
| query | 21559106 | 42274201 | 20715095 |
| update | 10387351 | 28514541 | 18127190 |
| delete | 17259 | 39827 | 22568 |
| getmore | 72954395 | 202198154 | 129243759 |
| command | 133147028 | 315243043 | 182096015 |
| total | 238954477 | 591127768 | 352173291 |

### Operation latencies

Average latency per operation is derived from the cumulative `opLatencies` counters. MongoDB stores those counters in microseconds, but the report displays them in milliseconds. The window average reflects only operations that occurred during the captured timeframe.

| Category | Ops in window | Throughput (ops/s) | Avg latency in window (ms) | Lifetime avg latency (ms) |
| --- | ---: | ---: | ---: | ---: |
| reads | 149,957,802 | 1,574.8 | 11.774 ms | 49.764 ms |
| writes | 19,126,730 | 200.9 | 6.416 ms | 30.226 ms |
| commands | 182,085,960 | 1,912.2 | 0.603 ms | 1.438 ms |
| transactions | 0 | 0.0 | N/A | N/A |

### Hardware & resource metrics

### Memory

| Metric | Start | End | Min | Max | Avg |
| --- | ---: | ---: | ---: | ---: | ---: |
| Resident memory (MiB) | 145845 | 144366 | 144366 | 145869 | 145225.1 |
| Virtual memory (MiB) | 197683 | 197759 | 197680 | 198446 | 197756.9 |
| Page faults (cumulative) | 23381 | 29010 | 23381 | 29010 | 26286.5 |
| Page faults during window | 5,629 | | | | |
| System memory utilization (%) | 31.19 | 30.88 | 30.86 | 31.43 | 31.06 |
| System memory cached (MiB) | 83163.7 | 84382.8 | 82778.8 | 84415.7 | 83538.7 |
| System memory free (MiB) | 275033.6 | 275504.1 | 272961.1 | 276242.6 | 275428.8 |
| System memory available (MiB) | 354435.0 | 356017.5 | 353150.5 | 356103.3 | 355104.7 |

### CPU utilization

Estimated from FTDC `systemMetrics.cpu` cumulative counters. Only normalized per-core utilization is shown to keep the report focused on comparable CPU saturation across hosts.

| Metric | Start | End | Min | Max | Avg |
| --- | ---: | ---: | ---: | ---: | ---: |
| Context switches (cumulative) | 4,239,181,498 | 6,603,153,210 | 4,239,181,498 | 6,603,153,210 | 5,414,217,556.4 |
| Context switches during window | 2,363,971,712 | | | | |
| Avg context switches/s | 24,825.12 | | | | |

### WiredTiger cache

Configured cache size: **250.99 GiB**

| Metric | Start | End | Min | Max | Avg |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bytes in cache | 105.89 GiB | 99.81 GiB | 99.66 GiB | 105.95 GiB | 104.04 GiB |
| Cache fill ratio (%) | 42.19 | 39.77 | 39.71 | 42.21 | 41.45 |
| Dirty bytes | 64.69 MiB | 89.57 MiB | 212.93 KiB | 254.04 MiB | 78.38 MiB |
| Dirty ratio (%) | 0.0252 | 0.0349 | 0.0001 | 0.0988 | 0.0305 |
| Bytes read into cache (window) | 1.68 TiB | | | | |
| Bytes written from cache (window) | 52.73 GiB | | | | |

### WiredTiger data handles

| Metric | Start | End | Min | Max | Avg |
| --- | ---: | ---: | ---: | ---: | ---: |
| Active data handles | 33,045 | 7,898 | 700 | 177,154 | 60,376.4 |

| Sweep metric | Start | End | Window total | Avg rate |
| --- | ---: | ---: | ---: | ---: |
| Connection sweep dhandles closed | 3,102,997 | 7,644,759 | 4,541,762 | 47.70/s |
| Session dhandles swept | 14,173,151 | 32,041,570 | 17,868,419 | 187.64/s |

### WiredTiger checkpoint preparation

| Metric | Start | End | Min | Max | Avg | Window total | Avg rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Prepare most recent time (ms) | 458 | 8 | 3 | 826,559 | 27,326.9 | N/A | N/A |
| Prepare total time (ms, cumulative) | 44,166,355 | 73,893,639 | 44,166,355 | 73,893,639 | 60,733,795.9 | 29,727,284 | 312.18 ms/s |

### Snapshot envelope details

| Boundary | Top-level start | serverStatus.localTime | Top-level end |
| --- | --- | --- | --- |
| First complete snapshot | 2026-08-12T03:10:48Z | 2026-08-12T03:10:48.003000Z | 2026-08-12T03:10:48.340000Z |
| Last complete snapshot | 2026-08-13T05:37:53Z | 2026-08-13T05:37:53.003000Z | 2026-08-13T05:37:53.338000Z |
