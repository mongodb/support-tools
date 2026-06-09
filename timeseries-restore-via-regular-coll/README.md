# Restore and Repair a Time Series Dump Containing Corrupt Data

## Warning

The scripts provided here are best run by those experienced with MongoDB, ideally with guidance from MongoDB Technical Support. They are provided without warranty or guarantee of any kind. If you do not have access to MongoDB Technical Support, consider reaching out to our community at [community.mongodb.com](https://community.mongodb.com) to ask questions.

Some adaptation of these scripts may be required for your use-case.

If you are using these scripts on your own, we strongly recommend:

* reading all instructions before attempting any action, and ensuring you are prepared for all steps.
* taking regular backups of the [dbpaths](https://docs.mongodb.com/manual/core/backups/#back-up-by-copying-underlying-data-files) of each node, and working off of backups as much as possible.
* reviewing the scripts themselves to understand their behavior.
* testing this process and all scripts on a copy of the environment it is to be run.
* for sharded clusters, disabling the balancer.

# Prerequisites

- Python 3.6 or later is required to run `convert_timeseries_mongodump_to_regular.py`.
- The mongosh script `timeseries-restore-via-regular-coll.js` should be run with a user that has [dbAdmin](https://www.mongodb.com/docs/manual/reference/built-in-roles/#mongodb-authrole-dbAdmin) permissions on the database(s) for the affected time-series collection(s).
- The target time series collection must already exist with the correct `timeField`, `metaField`, and bucket options. If it does not exist, create it before running the script.
- Bucket documents must be present in a regular MongoDB collection before the mongosh script can run. If you have a `mongodump` of the timeseries collection, use Phase 1 below to prepare them. If you already have bucket documents in a regular collection, skip directly to Phase 2.

# Overview of Procedure

**Phase 1 — Prepare the bucket documents from a mongodump** (skip if you already have a regular collection of bucket documents):

- `convert_timeseries_mongodump_to_regular.py` rewrites the dump so that `mongorestore` treats the bucket data as a regular collection. It copies the `system.buckets.<collection>.bson` file under a new name and strips the timeseries-specific metadata so the documents are restored as plain bucket records.
- Run `mongorestore` to load those bucket documents into the target database.

**Phase 2 — Restore the time series collection** using `timeseries-restore-via-regular-coll.js`:

- For each bucket document in the source collection, attempts a direct insert into `system.buckets.<tsColl>`. This succeeds for valid, uncorrupted buckets.
- If the direct insert fails (e.g. due to corrupt control metadata), attempts repair: unpacks the raw measurements from the bucket and re-packs them into fresh buckets via `$out` into a temporary time series collection, then copies those buckets into the destination.
- If repair also fails, stores the original bucket document in `badBucketsColl` for manual inspection, then moves on.

After each bucket is processed (whether copied, repaired, or recorded as bad), it is deleted from the source collection. This means the script is **resumable**: if it is interrupted, re-running it will continue from where it left off without double-processing any bucket.

**Warning**: The temporary collection provided must not be in active use. The script will drop and recreate it during repair operations.

**Warning**: This script directly modifies `<database>.system.buckets` collection —the underlying bucket store of the Time Series collection— in order to restore data. Under normal circumstances, users should not modify this collection.

Please contact [MongoDB Support](https://support.mongodb.com/welcome) with any questions or concerns regarding running these scripts.

# Running the Scripts

## Phase 1 — Prepare the Bucket Documents (if starting from a mongodump)

### 1. Convert the dump

`convert_timeseries_mongodump_to_regular.py` rewrites a timeseries collection's dump directory entry so that `mongorestore` will restore the raw bucket documents into a regular collection. Both plain and gzip-compressed (`mongodump --gzip`) dumps are supported.

```
python convert_timeseries_mongodump_to_regular.py \
    <dump_dir> \
    <db_name> \
    <timeseries_collection_name> \
    <destination_regular_collection_name>
```

Example:

```
python convert_timeseries_mongodump_to_regular.py \
    ./dump \
    mydb \
    weather \
    weather_buckets
```

This writes two new files into the dump directory and prints the commands needed for the next steps:

```
Wrote:
  BSON:     dump/mydb/weather_buckets.bson
  metadata: dump/mydb/weather_buckets.metadata.json

Restore the bucket documents into a regular collection (Phase 2, step 1):
  mongorestore --db "mydb" --collection "weather_buckets" "dump/mydb/weather_buckets.bson"

Create the target timeseries collection before running the restore script (Phase 2, step 2):
  db.createCollection("weather", {
    timeseries: {
      timeField: "t",
      metaField: "host",
      bucketMaxSpanSeconds: 3600,
      bucketRoundingSeconds: 3600
    }
  })
```

The timeseries options in the `db.createCollection()` snippet reflect exactly what was in the original collection, with only the fields that were present. Copy this snippet for use in step 4 below.

If destination files already exist from a previous run, use `--overwrite` to replace them.

### 2. Restore the bucket documents into a regular collection

Use the `mongorestore` command printed by the script in step 1. For a plain dump:

```
mongorestore --db "mydb" --collection "weather_buckets" "dump/mydb/weather_buckets.bson"
```

For a gzip dump (produced by `mongodump --gzip`), the script prints the `--gzip` flag automatically:

```
mongorestore --gzip --db "mydb" --collection "weather_buckets" "dump/mydb/weather_buckets.bson.gz"
```

---

## Phase 2 — Restore the Time Series Collection

### 3. Connect to your cluster using [mongosh](https://www.mongodb.com/docs/mongodb-shell/)

```
mongosh --uri <URI>
```

### 4. Ensure the target time series collection exists

The collection must exist with the same `timeField`, `metaField`, and bucket options as the original. If you ran step 1, use the `db.createCollection()` snippet it printed. Otherwise create the collection manually with the correct options:

```
use <database>

db.createCollection("weather", {
  timeseries: {
    timeField: "t",
    metaField: "host",   // omit if the original had no metaField
  }
})
```

### 5. Load the script `timeseries-restore-via-regular-coll.js`

```
load("timeseries-restore-via-regular-coll.js")
```

### 6. Call `runCopyWithRepair`

```
use <database>

runCopyWithRepair(
    db,                   // db handle for the target database
    "weather_buckets",    // regular collection containing the bucket documents
    "weather",            // target time series collection (must already exist)
    "tmp_ts_repair",      // temporary TS collection used during repair (will be created/dropped)
    "weather_badBuckets"  // collection where unrepaired buckets will be stored
)
```

The script prints progress as it runs and a summary on completion:

```
Starting copy from 'mydb.weather_buckets' to 'mydb.system.buckets.weather' ...
Copy + validation + repair phase complete.
  Total processed buckets: 1200
  Total repaired buckets:  47
  Total unrepaired (bad):  3
Corrupted/unrepaired buckets are stored in 'mydb.weather_badBuckets'.
```

### 7. Review unrepaired buckets (if any)

Buckets that could not be restored are recorded in `badBucketsColl` with their original document and the error encountered:

```
db.weather_badBuckets.find().pretty()
```

Each document has the form:

```
{
  _id: <original bucket _id>,
  originalBucket: { ... },
  error: { ... }
}
```

These buckets represent measurements that could not be recovered automatically and require manual inspection.

### 8. (Optional) Re-enable the balancer
