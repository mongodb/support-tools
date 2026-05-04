# SERVER-85346 Detection Guide

**Purpose:** Determine whether a customer's sharded cluster contains cross-shard duplicate documents caused by SERVER-85346.  
**Safety:** Both scripts are **read-only**. They do not modify any data and are safe to run on production clusters.

---

## What You Need

- `mongosh` installed locally ([download](https://www.mongodb.com/try/download/shell))
- The two script files: `find_candidate_collections.js` and `find_duplicates.js`
- The customer's `mongos` connection string (must connect to **mongos**, not a shard directly)

---

## Overview

The check runs in two steps to avoid running expensive aggregations on collections that cannot be affected.

| Step | Script | Time | What it does |
|------|--------|------|--------------|
| 1 | `find_candidate_collections.js` | Seconds | Metadata scan — finds collections that *could* be affected |
| 2 | `find_duplicates.js` | Minutes to hours | Aggregation — confirms whether duplicates actually exist |

If Step 1 finds no candidates, **stop — the cluster is not affected**. Only proceed to Step 2 for the collections listed by Step 1.

---

## Step 1 — Find Candidate Collections

```bash
mongosh "mongodb://<mongos-host>:<port>" --quiet -f find_candidate_collections.js
```

This completes in seconds. It scans index metadata across all sharded collections — no aggregations are run.

### Output: no candidates found

```
Collections scanned:     12
Candidate indexes found: 0
Collections to check:    0

==> No sharded collections with non-simple-collation indexes found.
```

**The cluster is NOT affected. No further action needed.**

### Output: candidates found

```
── mydb.orders
   Shard key: {"customerId":1}
   Index: name_idx  key: {"customerId":1,"name":1}  unique: yes  collation: {"locale":"en_US","strength":2}

Collections scanned:     12
Candidate indexes found: 1
Collections to check:    1

==> Run find_duplicates.js to check these collection(s) for actual duplicates.
```

**One or more collections need to be checked. Proceed to Step 2.**

Note down the namespace(s) listed (format: `database.collection`). You will use them in Step 2.

---

## Step 2 — Check for Actual Duplicates

Run this once per candidate collection identified in Step 1. Targeting one collection at a time is strongly recommended — it gives clearer output and lets you stop as soon as you find an affected collection.

### Check a single collection (recommended)

Replace `mydb.orders` with the namespace from Step 1:

```bash
mongosh "mongodb://<mongos-host>:<port>" \
  --eval 'const TARGET_NS="mydb.orders";' \
  --quiet -f find_duplicates.js
```

### Check all candidate collections at once

```bash
mongosh "mongodb://<mongos-host>:<port>" --quiet -f find_duplicates.js
```

> **Note:** On large collections this aggregation can take a long time and consume significant server resources. Check with the customer before running on a busy cluster.

### Output: no duplicates

```
Duplicate groups found:   0

==> No cross-shard collation duplicates found.
```

Exit code: `0`. **This collection is NOT affected.**

### Output: duplicates found

```
   Index: name_idx
     Collation: {"locale":"en_US","strength":2}
     Result: 2 duplicate group(s) found:

       Key values: {"name":"John Smith"}
       Count:      2
       Sample _ids: [ObjectId("665a1b..."), ObjectId("665a1c...")]

Duplicate groups found:   2
Affected collections:     mydb.orders

==> DUPLICATES DETECTED — this cluster is affected by SERVER-85346.
```

Exit code: `1`. **This collection IS affected.** See [What to Collect](#what-to-collect-when-affected) below.

---

## Verdict Summary

| Step 1 result | Step 2 result | Verdict |
|---------------|---------------|---------|
| No candidates | — | **NOT AFFECTED** |
| Candidates found | No duplicates in any | **NOT AFFECTED** |
| Candidates found | Duplicates in at least one | **AFFECTED** |

---

## What to Collect When Affected

Before closing the session, capture the full output of both scripts:

```bash
mongosh "mongodb://<mongos-host>:<port>" --quiet -f find_candidate_collections.js \
  | tee find_candidate_collections_output.txt

mongosh "mongodb://<mongos-host>:<port>" --quiet -f find_duplicates.js \
  | tee find_duplicates_output.txt
```

The output includes:
- The affected namespace(s)
- The index name, key, and collation
- The number of duplicate groups
- Sample `_id` values for each group

Attach both `.txt` files to the support case.

---

## Troubleshooting

**"command not found: mongosh"**  
Download mongosh from https://www.mongodb.com/try/download/shell and ensure it is on your `PATH`, or prefix every command with the full path:
```bash
/path/to/mongosh "mongodb://..." --quiet -f find_candidate_collections.js
```

**"Authentication failed" or "not authorized"**  
The user needs at least `read` on all databases and `read` on the `config` database. Ask the customer to connect with a user that has the built-in `readAnyDatabase` role (or `clusterMonitor`).

**Connection times out / cannot connect**  
Confirm the customer is providing the `mongos` address and port, not a shard or config server address. The scripts query `config.collections` which is only accessible via mongos.

**Step 2 runs for a very long time**  
The aggregation scans every document in the collection. On multi-terabyte collections this is expected. Use `TARGET_NS` to run one collection at a time so you can report partial results. Ask the customer if there is a maintenance window available.

**WARNING lines in the output**  
Lines like `WARNING: could not list indexes for db.coll` mean that collection was skipped. Note them in the case but they do not affect the verdict for other collections.
