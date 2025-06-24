# Repair Internal Buckets in Time Series Collections with Clamp to Min/Max

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

Please see [SERVER-103328](https://jira.mongodb.org/browse/SERVER-103328) for the affected versions. Users can determine if they have been impacted by running [`validate`](https://www.mongodb.com/docs/manual/reference/command/validate/) on their Time Series collections and checking the `validate.errors` field to determine if there are time series buckets with mismatching min/max metadata detected.

The validation command [can be very impactful](https://www.mongodb.com/docs/manual/reference/method/db.collection.validate/#performance). To minimize the performance impact of running validate, issue validate to a secondary and follow [these steps](https://www.mongodb.com/docs/manual/reference/method/db.collection.validate/#performance:~:text=Validation%20has%20exclusive,the%20hidden%20node). 

Example `validate` run on a standalone/replica set:
```
// Call validate on a mongod process for replica sets. 
coll.validate();

// The error field detects buckets with mismatching min/max. 
{
"ns" : "db.system.buckets.coll",
...
"errors" : [
"Detected one or more documents in this collection incompatible with time-series specifications. For more info, see logs with log id 6698300."
],
...
}
```

Example `validate` run on a sharded cluster:

```
// Call validate on mongos for sharded clusters.
coll.validate();

// The error field detects buckets with mismatching min/max.
// For sharded clusters, this output is an object with a result for every shard in 
// the "raw" field.
{
	"ns" : "db.system.buckets.coll",
	...
"errors" : [
"Detected one or more documents in this collection incompatible with time-series specifications. For more info, see logs with log id 6698300."
],
...
"raw" : {
	"shard-0-name" : {
		"ns" : "db.system.buckets.coll"
		...
"errors" : [
"Detected one or more documents in this collection incompatible with time-series specifications. For more info, see logs with log id 6698300."
],
...
},
"shard-1-name" : { ... }, ...
}
}
```

Inspect log lines with id `6698300` and ensure the reason contains the following string: `Mismatch between time-series control and observed min or max`.

```
{"t":{"$date":"2025-06-24T15:32:34.190-04:00"},"s":"W",  "c":"STORAGE",  "id":6698300, "ctx":"conn71","msg":"Document is not compliant with time-series specifications","attr":{"namespace":"db.system.buckets.coll","recordId":"6464130bc80b3647a84cc41e5d","reason":{"code":2,"codeName":"BadValue","errmsg":"Mismatch between time-series control and observed min or max for field doubleType. Control had min doubleType: 3.1 and max doubleType: 3.14159265359, but observed data had min { doubleType: 3.14159265359 } and max { doubleType: 3.14159265359 }."}}}
```

The `_id` of the affected bucket can be derived from the `recordId` field by removing the `64` prefix: `"recordId":"6464130bc80b3647a84cc41e5d"` corresponds to `_id` of `ObjectId('64130bc80b3647a84cc41e5d')` which is the input to the validation script.

# Repair Time Teries Bucket with Clamp to Min/Max

## Overview of procedure

The script offers a semi-transactional repair of time series buckets with clamping of metrics of the double type to the existing min and max information stored in the bucket. The repair will appear transactional on the time series collection but uses non-transactional steps on a temporary collection internally.

The script does not offer a full data recovery for users impacted by [SERVER-103328](https://jira.mongodb.org/browse/SERVER-103328) but is a best-effort attempt to minimize the error due to this bug by clamping the data to the range stored in the bucket as min and max for every metric. 

The full steps are as follows for each bucket in the time series collection to repair:
- Mark bucket as ineligible for writes for inserts, updates and delete operations.
- Unpack data from bucket and recursively clamp all elements of the double type to the stored min and max in the control field.
- Re-pack the clamped data into new buckets in a temporary time series collection.
- Transactionally delete the old bucket and insert the new buckets from the temporary collection.
- Cleanup the temporary collection.

**Warning**: The temporary collection provided should not exist prior to running this script. As part of the script all existing data in the temporary collection will be deleted. 

**Warning**: This script directly modifies `<database>.system.buckets` collection —the underlying bucket store of the Time Series collection—in order to remediate any problems. Under normal circumstances, users should not modify this collection. 

**Warning**: This script directly modifies the content of the user data stored inside a Time Series bucket. It is very important to perform a backup of the bucket before using this script. 

Please contact [MongoDB Support](https://support.mongodb.com/welcome) with any questions or concerns regarding running this script. 

## Running the script

### 1. Connect to your sharded cluster using [mongosh](https://www.mongodb.com/docs/mongodb-shell/):

```
mongosh --uri <URI>
```

### 2. Load the script `timeseries_bucket_repair_clamp_to_control.js`

```
load("timeseries_bucket_repair_clamp_to_control.js")
```

### 3. Repair bucket by bucket _id

```
use <database>

repairTimeseriesBucketWithClampToControl(ObjectId('<12-byte-bucket-id>'), collectionName, temporaryCollectionName) // single bucket version

repairTimeseriesBucketWithClampToControl([ObjectId('<12-byte-bucket-id>'), ...], collectionName, temporaryCollectionName) // multi bucket version
```

Example:

```
repairTimeseriesBucketWithClampToControl(ObjectId('6695218802c836d8453a6e21'), "timeseriesColl", "nonExistingCollToUseAsTemp");
```

### 5. (Optional) Re-enable the balancer.
