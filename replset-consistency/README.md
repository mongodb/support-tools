# Replica Set Consistency Validation

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

This process provides for identifying and resolving data inconsistencies between MongoDB replica set members, above and beyond what is currently supported by existing and documented `validate` and `dbHash` commands.

The primary use-cases for this process are when:

* a MongoDB replica set has undergone an unsafe upgrade path identified by [WT-8395](https://jira.mongodb.org/browse/WT-8395), a defect which can introduce data inconsistencies when upgrading from versions 4.4.3-4.4.4 directly to 4.4.8-4.4.10 or 5.0.2-5.0.5.
* all nodes of a MongoDB replica set have been separately impacted by [WT-7995](https://jira.mongodb.org/browse/WT-7995), [WT-7984](https://jira.mongodb.org/browse/WT-7984) on versions 4.4.2-4.4.8 and 5.0.0-5.0.2, and validate() output alone is not sufficient to rule out document-level inconsistencies between nodes.

**Warning**: Use this process with care and perform backups before proceeding. Be certain about what bug you are responding to, and be familiar with the details of that bug. This process involves scripts which cause load on and perform writes to your cluster. In particular, `repair_checked_documents.py` issues delete operations against user collections, depending on options provided when it is run.

## Remediation components

The overall remediation process relies on a combination of `mongod` database commands and scripts in this directory.

* The [validate database command](https://docs.mongodb.com/manual/reference/method/db.collection.validate/), optionally scripted for all databases/collections in `validate.js`.
* The [dbCheck database command](https://github.com/mongodb/mongo/blob/master/src/mongo/db/repl/dbcheck.idl), optionally scripted for all databases/collections in `dbcheck.js`:
  * a new server command, run per collection.
  * on each replica set node, generates hashes at points in time for ranges of documents.
  * outputs results to a non-replicated collection on each node (in each node's `local` database).
  * secondaries report inconsistencies with the primary.
* The `scan_checked_replset.js` javascript script for the legacy mongo shell ("mongo"):
  * consumes dbCheck output on each node.
  * uses specific ranges of inconsistencies reported by dbCheck on secondaries to identify specific differing documents.
  * writes results to new databases/collections in the cluster.
  * each collection on each node includes that node's version of the differing document (or no document, if that node is missing a document).
* The `repair_checked_documents.py` python3 script:
  * consumes scan_checked_replset.js script output.
  * resolves inconsistencies by overwriting documents according to a consensus between replica set nodes, depending on the strategy specified.
  * **Importantly**: `repair_checked_documents.py` restores the state of inconsistent documents as of the time they were backed up by `scan_checked_replset.js`. If the system is receiving writes, between the start of `scan_checked_replset.js` and `repair_checked_documents.py` those writes could be undone when `repair_checked_documents.py` remediates based on the state of the document at the time it was archived during `scan_checked_replset.js`.

## Pre-requisites

To perform this process, you will need to:

* Upgrade your cluster to MongoDB 4.4.11+ or 5.0.6+.
* Create on your cluster a database user that can:
  * read and write to any database
  * read the 'local.system.healthlog' collection
  * read and write to the '__corruption_repair.unhealthyRanges' collection
  * issue the following commands:
    * applyOps
    * listDatabases
    * listCollections
    * validate
    * dbCheck
  * Note that additional explicit privileges to read and write to system collections may be needed
* Prepare a machine for script execution with:
  * The (legacy) mongo shell
  * python3
  * the (latest) pymongo MongoDB driver
  * Network access to all members of the replica set being remediated

```
db.adminCommand({
  createRole: "remediationAdmin", 
  roles: [ "clusterManager", "clusterMonitor", "readWriteAnyDatabase"],
  privileges: [
    { resource: {cluster: true}, 
      actions: ["applyOps", "listDatabases", "serverStatus"] },
    { resource: {db: "local", collection: "system.healthlog"}, 
      actions: ["find"] },
    { resource: {db: "__corruption_repair", collection: "unhealthyRanges"}, 
      actions: ["find", "insert", "update", "remove", "createCollection", "dropCollection", "createIndex", "dropIndex"]
    },
    { resource: { anyResource: true }, 
      actions: ["listCollections", "validate"] },
  ]
});

db.getSiblingDB("admin").createUser({user: "remediate", pwd: "<password>", roles: [{role: "remediationAdmin", db: "admin"}]})
```

## Important notes:

False positives (inconsistencies that are not a concern) can occur on collections with TTL indexes, because MongoDB does not synchronize the removal of TTL documents between nodes.

# Remediation Steps

The overall high level process is:

1. Use a combination of the `validate` command and the `reIndex` command to ensure the `_id` index is consistent in all collections on all nodes.
1. For each collection in the cluster:
    1. Run `dbCheck` to generate initial inconsistency information.
    1. Stop writes to the collection.
    1. Run `scan_checked_replset.js` to generate specific inconsistency information.
    1. Run `repair_checked_documents.py` to resolve the identified inconsistencies, or resolve them manually.
    1. Optionally, re-run `dbCheck` to confirm consistency
    1. Resume writes to the collection.

## Validate

For each node, run `validate` on all collections on all nodes. `validate.js` runs validate on every collection of a given node.

On each node with validation issues, any “missing index entries” for the `_id` index must be fixed using [`reIndex`]|(https://docs.mongodb.com/manual/reference/method/db.collection.reIndex/) prior to running `dbCheck`. Other index inconsistencies, including extra entries in the `_id` index, do not need to be addressed prior to `dbCheck` (but will not necessarily be resolved by this remediation).

## Check and Remediate

For each collection on your replica set cluster:

### 1. Run dbCheck

Be prepared to monitor the performance of the cluster while `dbCheck` is active. Be aware of the following:

* dbCheck's `currentOp` entry can be seen using:

```
db.currentOp({desc: "dbCheck", $all: true})
```
* unacceptable, increasing replication lag and/or unacceptable operation latency can occur. Reduce or eliminate this risk by tuning the following [parameters to the dbCheck command](https://github.com/mongodb/mongo/blob/master/src/mongo/db/repl/dbcheck.idl):
    * `maxCountPerSecond`: Limits the rate of documents scanned by dbCheck
    * `batchWriteConcern.wtimeout`: Configures how long the primary waits for secondaries to complete their batches before moving onto the next batch.

**Most importantly**:

dbCheck writes information to `local.system.healthlog` on each node. This is a capped collection that could roll over during `dbCheck`. If this happens, explicitly create a larger capped `local.system.healthlog` and re-run `dbCheck`.

To check when `dbCheck` starts and finishes on a collection, run the following queries on all nodes:

```
db.getSiblingDB("local").system.healthlog.findOne({operation: "dbCheckStart"})
db.getSiblingDB("local").system.healthlog.findOne({operation: "dbCheckStop"})
```

It is important to check on all nodes as the contents on each node can vary, and may roll over separately.

If `local.system.healthlog` does not contain a "dbCheckStart" document for the collection you're running `dbCheck` on, `local.system.healthlog` has rolled over and subsequent scripts will not have complete information. 

If `dbCheck` is run using `dbcheck.js`, you may optionally specify an `authInfo` object, with the user created above, to automatically check if the healthlog has rolled over. Omitting this object will not accurately check if the healthlog has rolled over on each secondary.

When you are ready, run `dbCheck`, specifying a write concern equal to the number of data-bearing nodes (X) in the replica set, and our recommended `wtimeout` of `1000`.

```
db.getSiblingDB(<dbName>).runCommand({
  "dbCheck": <collName>,
  "batchWriteConcern": { "w": <X>, "wtimeout": 1000}
})
```

## 2. Run the scanning script
`scan_checked_replset.js`

This script uses the information output by dbCheck and uses it to identify specific inconsistencies. It records information in the `__corruption_repair.unhealthyRanges` collection and makes "backup collections" of inconsistent documents in your cluster.

Backup collections are named with a `<dbName>.dbcheck_backup.<collName>.<node_id>` convention, where `dbName`, `collName`, and `node_id` refer to the location of the document.

When you are ready:

**Stop writes to the collection or collections that have been dbChecked and are to be scanned and remediated**. If writes continue, they may be undone when `repair_checked_documents.py` remediates based on the state of the document at the time it was archived during `scan_checked_replset.js`.

From the primary node with the user created as a prerequisite above, run the scanning script. Note that the `--eval` argument requires escaped quotes within the `authInfo` object.

```
mongo --host <primaryHostAndPort> --eval "authInfo={\"user\":\"remediate\", \"pwd\":\"password\"}" scan_checked_replset.js | tee scan.txt_`date +"%Y-%m-%d_%H-%M-%S"`
```

Once the script is complete, the following query lists collections with inconsistencies:

```
db.getSiblingDB("__corruption_repair").unhealthyRanges.aggregate([{$group: {"_id": { "db": "$_id.db", "col": "$_id.collection" }}}])
```

## 3. Run the remediation script
`repair_checked_documents.py`

**WARNING:** Actions in this section can issue writes to your cluster.

By default, `repair_checked_documents.py` operates in dry-run mode. Use dry-run mode to become familiar with the actions the script will take. Consider the following options:
* `--strategy` tells the script what automatic actions to take. Select a strategy that makes sense for you. Read the script for more information.
* `--verbose` to see how each inconsistency has been resolved.
* `--fallback ask` ensures you are prompted for action when a given strategy cannot automatically determine a course of action.

This example uses a strategy of `majority` and performs a dry-run:

```
python3 repair_checked_documents.py <mongoUri> --strategy majority | tee remediation.txt_`date +"%Y-%m-%d_%H-%M-%S"`
```

Once satisfied by the results of the dry run, perform remediation with `--no-dryrun`.

**WARNING:** This action can issue writes to your cluster.

```
python3 repair_checked_documents.py <mongoUri> --strategy majority --no-dryrun --verbose | tee remediation.txt_`date +"%Y-%m-%d_%H-%M-%S"`
```

The script output will indicate if documents have been skipped. To remediate previously skipped documents, run the script again while:

* omitting any `--strategy` argument, to run in interactive mode, or
* specifying `--fallback ask` in addition to your chosen strategy, to ensure you are prompted when the chosen strategy cannot make a determination.

## 4. Confirm inconsistencies are resolved

After completing remediation, the cluster will be in a consistent state where no further dbChecks are needed. However, if general reassurance is desired or you suspect an issue during this process, you can perform a final full or partial dbCheck.

For a full check, use the instructions above in `Remediation > Check and Remediate > Run dbCheck`

To perform a partial dbCheck on the ranges that were marked inconsistent by the scanning script, use the following steps:

1. Query the `__corruption_repair.unhealthyRanges` collection to find ranges reported as inconsistent:

```
> db.getSiblingDB("__corruption_repair").unhealthyRanges.find({}, {_id:1}).limit(1)
{ "_id" : { "db" : "<dbName>", "collection" : "<collName>", "minKey" : <key_0>, "maxKey" : <key_1> } }
```

1. Run dbCheck specifying minKey and maxKey ranges:

```
db.getSiblingDB("<dbName>").runCommand({dbCheck: "<collName>", minKey: <key_0>, maxKey: <key_1>})
```

1. Run the scanning script again and verify there are no inconsistent ranges reported in `__corruption_repair.unhealthyRanges`.

When remediation is complete, resume writes to the collection(s) being remediated. It is safe to drop the `<dbName>.dbcheck_backup.<collName>.<node_id>` collections, but we recommend taking a backup of them before doing so.

## 5. Resolve any remaining index inconsistencies

Now that document data is confirmed consistent, and if `validate{}` previously indicated index inconsistencies, perform an initial sync of all affected nodes in sequence, to ensure indexes are rebuilt.

# License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)

# Disclaimer

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