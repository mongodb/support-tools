# Troubleshoot Bucket Version Mismatch in Time Series Collections

For more context on this issue, see [SERVER-94471](https://jira.mongodb.org/browse/SERVER-94471).

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

- This script should be run with a user that has [dbAdmin](https://www.mongodb.com/docs/v6.0/reference/built-in-roles/#mongodb-authrole-dbAdmin) permissions on the database(s) for the affected time-series collection(s).
-  If running on Atlas:
   - We have already reached out to impacted customers. If we have reached out, you can skip the [Determine if You're Impacted section](#Determine-if-You're-Impacted) and start taking the steps under the [Remediation section](#remediation).
   - Additionally, we recommend using the [Atlas Admin](https://www.mongodb.com/docs/atlas/security-add-mongodb-users/#built-in-roles) role.

# Determine if You're Impacted

Please see [SERVER-94471](https://jira.mongodb.org/browse/SERVER-94471) for the affected versions. Users can determine if they have been impacted by running [`validate`](https://www.mongodb.com/docs/v7.0/reference/command/validate/) on their Time Series collections and checking the `validate.errors` field to determine if there are buckets with mismatched versions. 
The validation command [can be very impactful](https://www.mongodb.com/docs/v7.0/reference/method/db.collection.validate/#performance). To minimize the performance impact of running validate, issue validate to a secondary and follow [these steps](https://www.mongodb.com/docs/v7.0/reference/method/db.collection.validate/#performance:~:text=Validation%20has%20exclusive,the%20hidden%20node). 

## Validation Results for v8.1+

Example `validate` run on a standalone/replica set:
```
// Call validate on a mongod process for replica sets. 
coll.validate();
// For v8.1+, the errors field detects bucket version mismatch.
{
"ns" : "db.system.buckets.coll",
...
"errors" : [
    Detected one or more documents in this collection incompatible with time-series
    specifications. For more info, see logs with log id 6698300.,
    ...
],
...
}
```
with the logs:
```
..."c":"STORAGE",  "id":6698300, "ctx":"conn9","msg":"Document is not compliant with time-series specifications","attr":{..."reason":{"code":2,"codeName":"BadValue","errmsg":"Time-series bucket [...] field is not in ascending order"}}...
```
or 
```
..."c":"STORAGE",  "id":6698300, "ctx":"conn9","msg":"Document is not compliant with time-series specifications","attr":{..."reason":{"code":2,"codeName":"BadValue","errmsg":"Time-series bucket is v3 but has its measurements in-order on time"}}...
```
Example `validate` run on a sharded cluster:
```
// Call validate on mongos for sharded clusters.
coll.validate();
// For v8.1+, the errors field detects bucket version mismatch.
// For sharded clusters, this output is an object with a result for every shard in 
// the "raw" field.
{
	"ns" : "db.system.buckets.coll",
	...
"errors" : [
    Detected one or more documents in this collection incompatible with time-series
    specifications. For more info, see logs with log id 6698300.,
    ...
],
...
"raw" : {
	"shard-0-name" : {
		"ns" : "db.system.buckets.coll"
		...
"errors" : [
    Detected one or more documents in this collection incompatible with time-series
    specifications. For more info, see logs with log id 6698300.,
    ...
],
...
},
"shard-1-name" : { ... }, ...
}
}
```
with the logs:
```
..."c":"STORAGE",  "id":6698300, "ctx":"conn9","msg":"Document is not compliant with time-series specifications","attr":{..."reason":{"code":2,"codeName":"BadValue","errmsg":"Time-series bucket [...] field is not in ascending order"}}...
```
or 
```
..."c":"STORAGE",  "id":6698300, "ctx":"conn9","msg":"Document is not compliant with time-series specifications","attr":{..."reason":{"code":2,"codeName":"BadValue","errmsg":"Time-series bucket is v3 but has its measurements in-order on time"}}...
```

## Validation Results Before v8.1

Example `validate` run on a standalone/replica set:
```
// Call validate on a mongod process for replica sets. 
coll.validate();
// For versions below v8.1, the warnings field detects bucket version mismatch.
{
"ns" : "db.system.buckets.coll",
...
"errors" : [
    Detected one or more documents in this collection incompatible with time-series
    specifications. For more info, see logs with log id 6698300.,
    ...
],
...
}
```
with the logs:
```
..."c":"STORAGE",  "id":6698300, "ctx":"conn9","msg":"Document is not compliant with time-series specifications","attr":{..."reason":{"code":2,"codeName":"BadValue","errmsg":"Time-series bucket [...] field is not in ascending order"}}...
```
or 
```
..."c":"STORAGE",  "id":6698300, "ctx":"conn9","msg":"Document is not compliant with time-series specifications","attr":{..."reason":{"code":2,"codeName":"BadValue","errmsg":"Time-series bucket is v3 but has its measurements in-order on time"}}...
```
Example `validate` run on a sharded cluster:
```
// Call validate on mongos for sharded clusters.
coll.validate();
// For versions below v8.1, the warnings field detects bucket version mismatch.
// For sharded clusters, this output is an object with a result for every shard in 
// the "raw" field.
{
	"ns" : "db.system.buckets.coll",
	...
"errors" : [
    Detected one or more documents in this collection incompatible with time-series
    specifications. For more info, see logs with log id 6698300.,
    ...
],
...
"raw" : {
	"shard-0-name" : {
		"ns" : "db.system.buckets.coll"
		...
"errors" : [
    Detected one or more documents in this collection incompatible with time-series
    specifications. For more info, see logs with log id 6698300.,
    ...
],
...
},
"shard-1-name" : { ... }, ...
}
}
```
with the logs:
```
..."c":"STORAGE",  "id":6698300, "ctx":"conn9","msg":"Document is not compliant with time-series specifications","attr":{..."reason":{"code":2,"codeName":"BadValue","errmsg":"Time-series bucket [...] field is not in ascending order"}}...
```
or 
```
..."c":"STORAGE",  "id":6698300, "ctx":"conn9","msg":"Document is not compliant with time-series specifications","attr":{..."reason":{"code":2,"codeName":"BadValue","errmsg":"Time-series bucket is v3 but has its measurements in-order on time"}}...
```

# Remediation

## Rewrite Bucket Version in a Time Series Collections

While the script is running, the performance of operations on the time-series collection may be impacted. The script does a scan of the whole collection and performs updates on impacted buckets, which may result in a large load if many buckets are affected. 	

At a high level, the script remediates errors during collection validation by updating the bucket's version from v2 to v3 and vice versa if a v2 bucket has unsorted data, or if a v3 bucket has sorted data. 

The full steps are as follows. For each bucket in the time series collection:
- Detect if the bucket has bucket version mismatch.
- Change the buckets with bucket version mismatch to the correct version.
- Validate that there are no bucket version mismatches.

**Warning**: This script directly modifies `<database>.system.buckets` collection —the underlying buckets of the Time Series collection—in order to remediate performance issues. Under normal circumstances, users should not modify this collection. 

Please contact [MongoDB Support](https://support.mongodb.com/welcome) with any questions or concerns regarding running this script. 
### Running the remediation script

#### 1. Modify the script by populating `collName` with the name of your collection

```
// ------------------------------------------------------------------------------------
// Populate collName with the time-series collection that failed validation due
// to v2/v3 timeseries buckets not in correct sorted/unsorted order
// respectively.
// ------------------------------------------------------------------------------------
```

#### 2. Connect to your sharded cluster using [mongosh](https://www.mongodb.com/docs/mongodb-shell/):

```
mongosh --uri <URI>
```

#### 3. Load the script `rewrite_timeseries_bucket_version_mismatch.js`

```
load("rewrite_timeseries_bucket_version_mismatch.js")
```

#### 4. Repeat steps 1-3 for each time-series collection that was affected.
