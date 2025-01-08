# Troubleshoot Mixed-Schema Buckets in Time Series Collections

For more context on this issue, see [SERVER-91194](https://jira.mongodb.org/browse/SERVER-91194).

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

Please see [SERVER-91194](https://jira.mongodb.org/browse/SERVER-91194) for the affected versions. Users can determine if they have been impacted by running [`validate`](https://www.mongodb.com/docs/v7.0/reference/command/validate/) on their Time Series collections and checking the `validate.warnings` field to determine if there are mixed-schema buckets detected.

The validation command [can be very impactful](https://www.mongodb.com/docs/v7.0/reference/method/db.collection.validate/#performance). To minimize the performance impact of running validate, issue validate to a secondary and follow [these steps](https://www.mongodb.com/docs/v7.0/reference/method/db.collection.validate/#performance:~:text=Validation%20has%20exclusive,the%20hidden%20node). 

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

# Remediation

## Properly Set the Internal Time Series Flag

For each impacted collection, users should set the `timeseriesBucketsMayHaveMixedSchemaData` flag to `true` via `collMod`. This will ensure that future queries on the collection return correct results. 

```
db.runCommand({ collMod: coll, timeseriesBucketsMayHaveMixedSchemaData: true });
```

After setting the flag on these collections, users may observe a performance regression that they deem unacceptable. They can then follow the next optional step of running `rewrite_timeseries_mixed_schema_buckets.js` to regain performance. 

## Rewrite Mixed-Schema Buckets in Time Series Collections (optional)

While the script is running, the performance of operations on the time-series collection may be impacted. The script does a scan of the whole collection and performs multiple reads and writes per mixed-schema bucket, which may result in a large load if many buckets are affected.  

At a high level, the script remediates performance by rewriting buckets from the mixed-schema format to the older schema.  The rewrite is done by unpacking the measurements of the problematic mixed-schema buckets and inserting those measurements back into the collection.

The full steps are as follows. For each bucket in the time series collection:
- Detect if the bucket has mixed-schema data.
- Re-insert the measurements of the mixed-schema bucket transactionally.
  - Unpack the measurements.
  - Insert the measurements back into the collection. These will go into new buckets.
  - Delete the mixed-schema bucket from the collection.

**Warning**: This script directly modifies `<database>.system.buckets` collection —the underlying buckets of the Time Series collection—in order to remediate performance issues. Under normal circumstances, users should not modify this collection. 

Please contact [MongoDB Support](https://support.mongodb.com/welcome) with any questions or concerns regarding running this script. 

### Running the remediation script

#### 1. Modify the script by populating `collName` with the name of your collection

```
// ------------------------------------------------------------------------------------
// Populate collName with the time-series collection with mixed-schema buckets.
// ------------------------------------------------------------------------------------
const collName = "your_collection_name";
```

#### 2. Connect to your sharded cluster using [mongosh](https://www.mongodb.com/docs/mongodb-shell/):

```
mongosh --uri <URI>
```

#### 3. Load the script `rewrite_timeseries_mixed_schema_buckets.js`

```
load("rewrite_timeseries_mixed_schema_buckets.js")
```

#### 4. Repeat steps 1-3 for each time-series collection that was affected.

#### 5. (Optional) Re-enable the balancer.
