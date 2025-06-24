# Repair internal Buckets in Time Series Collections

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

# Determine if You're Impacted

Users can determine if they have been impacted by running [`validate`](https://www.mongodb.com/docs/manual/reference/command/validate/) on their Time Series collections and checking the `validate.errors` and `validate.warnings` fields to determine if there are problems with time series buckets detected.

The validation command [can be very impactful](https://www.mongodb.com/docs/manual/reference/method/db.collection.validate/#performance). To minimize the performance impact of running validate, issue validate to a secondary and follow [these steps](https://www.mongodb.com/docs/manual/reference/method/db.collection.validate/#performance:~:text=Validation%20has%20exclusive,the%20hidden%20node). 

Example `validate` run on a standalone/replica set:
```
// Call validate on a mongod process for replica sets. 
coll.validate();

// The warnings field detects mixed-schema buckets. 
{
"ns" : "db.system.buckets.coll",
...
"warnings" : [
"Detected a Time Series bucket with mixed schema data"
],
...
}
```

Example `validate` run on a sharded cluster:

```
// Call validate on mongos for sharded clusters.
coll.validate();

// The warnings field detects mixed-schema buckets.
// For sharded clusters, this output is an object with a result for every shard in 
// the "raw" field.
{
	"ns" : "db.system.buckets.coll",
	...
"warnings" : [
"Detected a Time Series bucket with mixed schema data"
],
...
"raw" : {
	"shard-0-name" : {
		"ns" : "db.system.buckets.coll"
		...
"warnings" : [
"Detected a Time Series bucket with mixed schema data"
],
...
},
"shard-1-name" : { ... }, ...
}
}
```

# Repair Time Teries Bucket

## Overview of procedure

The script offers a semi-transactional repair of time series buckets. The repair will appear transactional on the time series collection but uses non-transactional steps on a temporary collection internally.

The full steps are as follows for each bucket in the time series collection to repair:
- Mark bucket as ineligible for writes for inserts, updates and delete operations.
- Unpack data from bucket and re-pack into new buckets in a temporary time series collection.
- Transactionally delete the old bucket and insert the new buckets from the temporary collection.
- Cleanup the temporary collection.

**Warning**: The temporary collection provided should not exist prior to running this script. As part of the script all existing data in the temporary collection will be deleted. 

**Warning**: This script directly modifies `<database>.system.buckets` collection —the underlying bucket store of the Time Series collection—in order to remediate any problems. Under normal circumstances, users should not modify this collection. 

Please contact [MongoDB Support](https://support.mongodb.com/welcome) with any questions or concerns regarding running this script. 

## Running the script

### 1. Connect to your sharded cluster using [mongosh](https://www.mongodb.com/docs/mongodb-shell/):

```
mongosh --uri <URI>
```

### 2. Load the script `timeseries_bucket_repair.js`

```
load("timeseries_bucket_repair.js")
```

### 3. Repair bucket by bucket _id

```
use <database>
repairTimeseriesBucket(ObjectId('<12-byte-bucket-id>'), collectionName, temporaryCollectionName) // single bucket version
repairTimeseriesBucket([ObjectId('<12-byte-bucket-id>'), ...], collectionName, temporaryCollectionName) // multi bucket version
```

Example:

```
repairTimeseriesBucket(ObjectId('6695218802c836d8453a6e21'), "timeseriesColl", "nonExistingCollToUseAsTemp");
```

### 5. (Optional) Re-enable the balancer.
