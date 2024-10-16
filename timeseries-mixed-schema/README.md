# Rewrite Mixed-Schema Buckets in Time Series Collections


## Warning

The scripts provided here are best run by those experienced with MongoDB, ideally with guidance from MongoDB Technical Support. They are provided without warranty or guarantee of any kind (see disclaimer below). If you do not have access to MongoDB Technical Support, consider reaching out to our community at [community.mongodb.com](community.mongodb.com) to ask questions.

Some adaptation of these scripts may be required for your use-case.

If you are using these scripts on your own, we strongly recommend:

* reading all instructions before attempting any action, and ensuring you are prepared for all steps.
* taking regular backups of the [dbpaths](https://docs.mongodb.com/manual/core/backups/#back-up-by-copying-underlying-data-files) of each node, and working off of backups as much as possible.
* reviewing the scripts themselves to understand their behavior.
* testing this process and all scripts on a copy of the environment it is to be run.
* for sharded clusters, disabling the balancer.

# Summary

This script can be used to optionally remediate performance after fixing the internal `timeseriesBucketsMayHaveMixedSchemaData` flag that was incorrectly set as a result of [SERVER-91194](https://jira.mongodb.org/browse/SERVER-91194). 

At a high level, the script remediates performance by rewriting buckets from the mixed-schema format to the older schema.

The rewrite is done by unpacking the measurements of the problematic mixed-schema buckets and inserting those measurements back into the collection.

The full steps are as follows. For each bucket in the time series collection:
- Detect if the bucket has mixed-schema data.
- Re-insert the measurements of the mixed-schema bucket transactionally.
  - Unpack the measurements.
  - Insert the measurements back into the collection. These will go into new buckets.
  - Delete the mixed-schema bucket from the collection.

**Warning**: This script directly modifies `<database>.system.buckets` collection —the underlying buckets of the Time Series collection—in order to remediate performance issues. Under normal circumstances, users should not modify this collection. 

Please contact [MongoDB Support](https://support.mongodb.com/welcome) with any questions or concerns regarding running this script. 

# Pre-requisites 
* Users should first follow the diagnosis and remediation sections as specified in as specified in [SERVER-91194](https://jira.mongodb.org/browse/SERVER-91194)'s User Summary Box. This includes first determining if they have been impacted by running `validate()` on their time series collections and setting the  `timeseriesBucketsMayHaveMixedSchemaData` flag to `true` for impacted collections.
* This script should be run with a user that has [dbAdmin](https://www.mongodb.com/docs/v6.0/reference/built-in-roles/#mongodb-authrole-dbAdmin) permissions on the database(s) for the affected time-series collection(s).
* If running on Atlas - we recommend using the [Atlas Admin](https://www.mongodb.com/docs/atlas/security-add-mongodb-users/#built-in-roles) role. 

# Usage

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
