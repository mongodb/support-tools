# Planner Settings Checker

This script collects MongoDB **query planner customizations** across all databases and
collections in a deployment and reports only the namespaces where a setting is actually
present. It is intended as a **pre-migration audit** so that planner customizations are
identified, reviewed, and (where appropriate) re-created on the destination cluster.

It runs in one of two modes:

| Mode | Mechanism | Applies to |
| --- | --- | --- |
| `indexFilters` | `planCacheListFilters` command | Legacy index filters (all supported versions) |
| `querySettings` | `$querySettings` aggregation stage | Query settings (**MongoDB 8.0+**) |

> **Why both?** Index filters are the legacy mechanism for constraining the query
> planner. Query settings are their modern, persistent replacement introduced in
> MongoDB 8.0. Depending on the source server version, planner customizations may live
> in one or the other.

---

## What the script does

### `indexFilters` mode (default)

1. Enumerates every database via `getDBs()`.
2. For each database, lists non-system collections (skips `system.*` and the internal
   `local` collections).
3. Runs `planCacheListFilters` against each collection.
4. Returns **only** collections that have one or more index filters set.

### `querySettings` mode

1. Runs a single `$querySettings` aggregation against the `admin` database.
2. Groups the returned settings by namespace (`db.collection`).
3. Returns the per-namespace settings.

### Output

Prints a JSON report including a timestamp, host, mode, a summary count, and the matching
results.

**Sample `indexFilters` output:**

```json
{
  "generatedAt": "2026-06-11T00:00:00.000Z",
  "host": "cluster0-shard-00-00.example.mongodb.net:27017",
  "mode": "indexFilters",
  "summary": { "collectionsWithIndexFilters": 1, "errorCount": 0 },
  "results": [
    {
      "db": "mydb",
      "collection": "users",
      "namespace": "mydb.users",
      "hasIndexFilters": true,
      "indexFilterCount": 1,
      "indexFilters": [ { "query": { "email": 1 }, "indexes": [ { "email": 1 } ] } ]
    }
  ],
  "errors": []
}
```

---

## Usage

```bash
# Index filters (default)
mongosh "<connection-string>" --quiet --eval 'var _mode="indexFilters"' get-planner-settings.js

# Query settings (MongoDB 8.0+)
mongosh "<connection-string>" --quiet --eval 'var _mode="querySettings"' get-planner-settings.js
```

If `_mode` is omitted it defaults to `indexFilters`. An invalid value prints usage and
exits with a non-zero code.

---

## Requirements

- **`indexFilters`**: privileges to enumerate databases/collections and run
  `planCacheListFilters` on the target collections.
- **`querySettings`**: MongoDB **8.0+** and cluster-admin level privileges to run the
  `$querySettings` aggregation against `admin`.

Per-database or per-collection errors (for example, due to restricted privileges) are
captured and skipped gracefully rather than aborting the run.

---

## Notes

- The script is **read-only**. It only issues diagnostic commands and does not modify any
  planner settings, indexes, or data.
- On clusters with a very large number of collections, `indexFilters` mode issues one
  command per collection; the run is lightweight but may take time at scale.

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
