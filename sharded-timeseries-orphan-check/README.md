# Check Sharded Time Series Orphans


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

This script can be used to identify and recover any documents within a sharded time series collection which were orphaned as a result of [SERVER-80203](https://jira.mongodb.org/browse/SERVER-80203). 

The `checkTimeseriesOrphansOnCluster()` function will query each shard of the sharded cluster to identify orphaned documents within [internal time series bucket collections](https://www.mongodb.com/docs/manual/core/timeseries-collections/#behavior) which are not a byproduct of a Sharded Cluster [range migration](https://www.mongodb.com/docs/manual/core/sharding-balancer-administration/#range-migration-procedure). The results of this function will be written to a collection of users choosing. 

The `stageOrphanedTimeSeriesDocumentsForRecovery()` function will move time series metadata to an unsharded version of the affected collection with the name of the users choosing. These collections can be used to re-insert documents into the original collection such that they will no longer be orphaned. 

Please contact [MongoDB Support](https://support.mongodb.com/welcome) with any questions or concerns regarding running this script. 

# Pre-requisites 

* This script requires that [Shard Local Database Users](https://www.mongodb.com/docs/v6.0/core/sharded-cluster-shards/#shard-local-users) with the [readWriteAnyDatabase](https://www.mongodb.com/docs/manual/reference/built-in-roles/#mongodb-authrole-readWriteAnyDatabase) and [clusterMonitor](https://www.mongodb.com/docs/v6.0/reference/built-in-roles/#mongodb-authrole-clusterMonitor) roles exist on each shard of the sharded cluster. This database user will be used to query each shard for time series documents that should reside on other shards.

* If running on Atlas - we recommend using the [Atlas Admin](https://www.mongodb.com/docs/atlas/security-add-mongodb-users/#built-in-roles) role. 

* The sharded cluster balancer should be disabled prior to running this script and remain disabled until all orphaned documents have been re-inserted into their appropriate shard. 

# Usage

#### 1. Update the script to configure the username and password of Shard Local database users

```
const credentialsForDirectConnection = {
    "username" : "my_username",
    "password" : "my_password", 
    "authSource" : "admin",
    "tls" : true/false
};
```

Note that MongoDB Atlas [requires TLS for client connections](https://www.mongodb.com/docs/atlas/reference/faq/security/#how-does-service-encrypt-my-data-)

#### 2. Connect to your sharded cluster using *mongosh*:

```
mongosh --uri <URI>
```

#### 3. Load the script `check_ts_coll_orphans.js`

```
load("check_ts_coll_orphans.js")
```

#### 4. Call `checkTimeseriesOrphansOnCluster()` while specifying the name of the collection into which to write results:

```
checkTimeseriesOrphansOnCluster(results_namespace)
```

Where `results_namespace` is the `database.collection` namespace into which the results of this script should be written. 

This script will write results to the namespace of your choosing. The contents of this collection will have the form: 

```
{
    _id: ObjectId("6557f6f199d169f0edafc6b1"),
    orphanDocData: {
        _id: ObjectId("60a37400b5a20f507250517e"),
        parentNamespace: 'test.system.buckets.weather',
        foundIn: 'shard01'
    }
}
```

Where: 

* `_id` : The `_id` of the document within the namespace provided by the user.
* `orphanDocData._id` : The `_id` of the orphaned time series bucket document on the shard where it currently resides (see `orphanDocData.foundIn`)
* `orphanDocData.parentNamespace` : The namespace of the time series bucket for the orphan document.
* `orphanDocData.foundIn` : The shard on which the orphaned document currently resides.

#### 5. Review the results of the script within the namespace that was specified

In particular, review: 

* The number of time series collections affected, and 
* The quanity of buckets documents which were orphaned, and
* The total size of documents which will need to be moved and re-inserted

These bucket documents will be re-inserted into a new collections - which will incur increased storage relative to the quantity of buckets being written. 

#### 6. Stage orphaned bucket documents for re-insertion

```
stageOrphanedTimeSeriesDocumentsForRecovery(resultsCollection, current_namespace, staging_namespace)
```

Where: 

* `resultsCollection` is the collection name containing the results generated by checkTimeseriesOrphansOnCluster()
* `current_namespace` is the namespace (db.collection) for the time series collection for which we are staging documents. 
* `staging_namespace` is the namespace (db.collection) of the temporary, unsharded collection to which orphaned documents will be written.

This function will create an unsharded timeseries collection at (`staging_namespace`) with the same time series options as the existing collection (`current_namespace`). Orphaned documents are queried from the shards on which they currently reside, be written into this the collection specified by `staging_namespace`, and finally be deleted from the shard on which they were residing. 

As part of this process - documents will be moved from each shard into the new `staging_namespace`. As such, it is important that the collection specified in `staging_namespace` is not dropped once documents have been moved. 

You may want to consider taking backups of the `staging_namespace` once this command completes. 

#### 7. Iterate through documents in the staging collections to re-insert documents back into the original collection

```
// For example - for a given collection named 'weather' with a temporary collection named 'temp_weather'
db.temp_weather.find().forEach(function(doc) {
    db.weather.insertOne(doc)
})
```

Depending on the quantity of documents affected - you may want to consider using [bulk writes](https://www.mongodb.com/docs/manual/reference/method/db.collection.bulkWrite/).

#### 8. Repeat steps 5 and 6 for each time series collection which was impacted.  

#### 9. (Optional) Drop the temporary collection(s) once all data has been re-inserted

#### 10. (Optional) Re-enable the balancer.
