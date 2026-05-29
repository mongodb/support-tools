# Repair Corrupt Buckets in Time Series Collections via a Regular Collection

## Warning

The scripts provided here are best run by those experienced with MongoDB, ideally with guidance from MongoDB Technical Support. They are provided without warranty or guarantee of any kind (see disclaimer below). If you do not have access to MongoDB Technical Support, consider reaching out to our community at [community.mongodb.com](community.mongodb.com) to ask questions.

Some adaptation of these scripts may be required for your use-case.

If you are using these scripts on your own, we strongly recommend:

* reading all instructions before attempting any action, and ensuring you are prepared for all steps.
* taking regular backups of the [dbpaths](https://docs.mongodb.com/manual/core/backups/#back-up-by-copying-underlying-data-files) of each node, and working off of backups as much as possible.
* reviewing the scripts themselves to understand their behavior.
* testing this process and all scripts on a copy of the environment it is to be run.
* for sharded clusters, disabling the balancer.

# Prerequisites

- This script should be run with a user that has [dbAdmin](https://www.mongodb.com/docs/manual/reference/built-in-roles/#mongodb-authrole-dbAdmin) permissions on the database(s) for the affected time-series collection(s).
- The target time series collection must already exist with the correct `timeField`, `metaField`, and bucket options. If it does not exist, create it before running the script.
- The bucket documents to repair must be present in a regular MongoDB collection. This is typically produced by converting a `mongodump` with `convert_timeseries_mongodump_to_regular.py` and loading with `mongorestore`.

# Overview of procedure

The script repairs time series buckets stored in a regular collection. For each bucket `_id` provided:

- Unpack the raw measurements from the bucket document in the source regular collection using `$_internalUnpackBucket`.
- Re-pack them into fresh, valid buckets via a temporary timeseries collection.
- Transactionally insert the repaired buckets into the target timeseries collection's bucket store.
- Clean up the temporary collection.

**Warning**: This function is intended for single-run targeted repair. Calling it a second time with the same bucket `_id` against an already-populated destination will insert duplicate measurements, because the temporary timeseries collection generates new bucket `_id`s on each run.

**Warning**: The temporary collection provided must not be in active use. The script will drop and recreate it during repair.

**Warning**: This script directly modifies `<database>.system.buckets` collection —the underlying bucket store of the Time Series collection— in order to restore data. Under normal circumstances, users should not modify this collection.

Please contact [MongoDB Support](https://support.mongodb.com/welcome) with any questions or concerns regarding running this script.

## Running the script

### 1. Connect to your cluster using [mongosh](https://www.mongodb.com/docs/mongodb-shell/)

```
mongosh --uri <URI>
```

### 2. Ensure the target time series collection exists

The collection must exist with the same `timeField`, `metaField`, and bucket options as the original. If it does not exist, create it:

```
use <database>

db.createCollection("your_timeseries_coll", {
  timeseries: {
    timeField: "t",
    metaField: "host",   // omit if the original had no metaField
  }
})
```

### 3. Load the script `timeseries_bucket_repair.js`

```
load("timeseries_bucket_repair.js")
```

### 4. Repair bucket by bucket _id

```
use <database>
repairTimeseriesBucketViaRegularColl(ObjectId('<12-byte-bucket-id>'), srcColl, tsColl, tempColl) // single bucket version
repairTimeseriesBucketViaRegularColl([ObjectId('<12-byte-bucket-id>'), ...], srcColl, tsColl, tempColl) // multi bucket version
```

Example:

```
repairTimeseriesBucketViaRegularColl(
    ObjectId('6695218802c836d8453a6e21'),
    "myBucketDump",          // regular collection containing the bucket documents
    "your_timeseries_coll",  // target timeseries collection (must already exist)
    "tmp_repair"             // temporary TS collection used during repair (will be dropped/recreated)
);
```

### 5. (Optional) Re-enable the balancer.
