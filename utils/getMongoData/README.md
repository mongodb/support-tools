MongoDB Support Tools
=====================

getMongoData.js
---------------

### Description

`getMongoData.js` is a utility for gathering information about how a running
MongoDB deployment has been configured and for gathering statistics about its
databases, collections, indexes, and shards.

For sample output, see [getMongoData.log](sample/getMongoData.log).

### Usage

To execute on a locally-running `mongod` or `mongos` on the default port (27017)
without authentication, run:

    mongo --quiet --norc getMongoData.js > getMongoData-output.json

To execute on a remote `mongod` or `mongos` with authentication (see the next
section for the minimum required permissions), run:

    mongo HOST:PORT/admin -u ADMIN_USER -p ADMIN_PASSWORD --quiet --norc getMongoData.js > getMongoData-output.json

If `ADMIN_PASSWORD` is omitted, the shell will prompt for the password.

To have the output be in a more human-readable (non-JSON format), modify the above
commands to include the following `--eval` option, as demonstrated for the local
execution:

    mongo --eval "var _printJSON=false;" getMongoData.js > getMongoData-output.log

To have a `mongos` for a sharded cluster output full details of chunk
distribution across shards, include `var _printChunkDetails=true` in the
`--eval` option:

    mongo --quiet --norc --eval "var _printChunkDetails=true; var _ref = 'Support Case NNNNN'" getMongoData.js > getMongoData-output.json

### More Details

`getMongoData.js` is JavaScript script which must be run using the `mongo` shell
against either a `mongod` or a `mongos`.

Minimum required permissions (see [MongoDB Built-In Roles](https://docs.mongodb.com/manual/reference/built-in-roles)):
* A database user with the `backup`, `readAnyDatabase`, and `clusterMonitor` roles. These are essentially read-only roles except the [backup](https://docs.mongodb.com/manual/reference/built-in-roles/#backup-and-restoration-roles) role allows writes to two MongoDB system collections - `admin.mms.backup` and `config.settings`. The `backup` role is necessary in order for the script to output the number of database users and user-defined roles configured.
* A root/admin database user may be used as well.

Example command for creating a database user with the minimum required permissions:

```
db.getSiblingDB("admin").createUser({
    user: "ADMIN_USER",
    pwd: "ADMIN_PASSWORD",
    roles: [ "backup", "readAnyDatabase", "clusterMonitor" ]
  })
```

The most notable methods, commands, and aggregations that this script runs are listed below.

**Server Process Config & Stats**
* [serverStatus](https://docs.mongodb.com/manual/reference/command/serverStatus)
* [hostInfo](https://docs.mongodb.com/manual/reference/command/hostInfo)
* [getCmdLineOpts](https://docs.mongodb.com/manual/reference/command/getCmdLineOpts)
* [buildInfo](https://docs.mongodb.com/manual/reference/command/buildInfo)
* [getParameter](https://docs.mongodb.com/manual/reference/command/getParameter/)

**Replica Set Config & Stats**
* [rs.conf()](https://docs.mongodb.com/manual/reference/method/rs.conf/)
* [rs.status()](https://docs.mongodb.com/manual/reference/method/rs.status/)
* [db.getReplicationInfo()](https://docs.mongodb.com/manual/reference/method/db.getReplicationInfo)
* [db.printSecondaryReplicationInfo()](https://docs.mongodb.com/manual/reference/method/db.printSecondaryReplicationInfo)

**Database Users and User-Defined Roles (the count only)**
* [db.system.users.count()](https://docs.mongodb.com/manual/reference/system-users-collection/) in the "admin" database
* [db.system.roles.count()](https://docs.mongodb.com/manual/reference/system-roles-collection/) in the "admin" databases

**Database, Collection, and Index Config & Stats**
* [listDatabases](https://docs.mongodb.com/manual/reference/command/listDatabases/)
* [db.getCollectionNames()](https://docs.mongodb.com/manual/reference/method/db.getCollectionNames/)
* [db.stats()](https://docs.mongodb.com/manual/reference/method/db.stats/)
* [db.getProfilingStatus()](https://docs.mongodb.com/manual/reference/method/db.getProfilingStatus/)
* [db.collection.stats()](https://docs.mongodb.com/manual/reference/method/db.collection.stats/)
* [db.collection.getShardDistribution()](https://docs.mongodb.com/manual/reference/method/db.collection.getShardDistribution/)
* [db.collection.getIndexes()](https://docs.mongodb.com/manual/reference/method/db.collection.getIndexes/)
* [$indexStats](https://docs.mongodb.com/manual/reference/operator/aggregation/indexStats/)

**Sharding Config & Stats**
* Queries and aggregations on various collections in the MongoDB [config database](https://docs.mongodb.com/manual/reference/config-database/), including the "version", "settings", "routers", "shards", "databases", "chunks", and "tags" collections.

**Queryable Encryption (QE) Config**
* [db.getCollectionInfos()](https://docs.mongodb.com/manual/reference/method/db.getCollectionInfos/)
* Performs queries and aggregations on QE collections and auxiliary collections in all databases. The output is an
array of objects, each containing information about a queryable encrypted collection.

### Additional Notes
* This script should take on the order of seconds to run.
* If your deployment has more than 2500 collections, this script will by default fail.

### License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)


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
