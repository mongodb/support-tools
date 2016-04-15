/**
 * indexStats.js - Utility to retrieve and aggregate collection index statistics for MongoDB 3.2+
 *
 *  DISCLAIMER
 *
 *  Please note: all tools/ scripts in this repo are released for use "AS
 *  IS" without any warranties of any kind, including, but not limited to
 *  their installation, use, or performance. We disclaim any and all
 *  warranties, either express or implied, including but not limited to
 *  any warranty of noninfringement, merchantability, and/ or fitness for
 *  a particular purpose. We do not warrant that the technology will
 *  meet your requirements, that the operation thereof will be
 *  uninterrupted or error-free, or that any errors will be corrected.
 *
 *  Any use of these scripts and tools is at your own risk. There is no
 *  guarantee that they have been through thorough testing in a
 *  comparable environment and we are not responsible for any damage
 *  or data loss incurred with their use.
 *
 *  You are responsible for reviewing and testing any scripts you run
 *  thoroughly before use in any non-testing environment.
 *
 *
 * LICENSE
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

var ConnectionManager = function(theDB) {
    this._localDB = theDB;
    this._globalAuthDoc = null;
    this.connections = {};
}

ConnectionManager.prototype.setAuth = function(user, pwd) {
    this._globalAuthDoc = {'user':user,'pwd':pwd};
}

ConnectionManager.prototype.getLocalDB = function() {
    return this._localDB;
}

ConnectionManager.prototype.copyDoc = function(doc) {
    var newDoc = {};
    for (var prop in doc) {
        newDoc[prop] = doc[prop];
    }
    return newDoc;
}

ConnectionManager.prototype.getConnection = function(server) {
    if (this._globalAuthDoc){
        var auth = true;
    } else {
        var auth = false;
    }

    if (!this.connections[server]) {
        var conn = new Mongo(server);
        var admin = conn.getDB("admin");

        if (auth) {
            var authDoc = this.copyDoc(this._globalAuthDoc);
            if (admin.auth(authDoc) != 1){
                return null;
            }
        }

        this.connections[server] = {'conn':conn,'auth':auth};
        return conn;
    }

    return this.connections[server].conn;
}

IndexStatsAccumulator = function(connectionManager, ns) {
    this._connectionManager = connectionManager;
    this._mongo = connectionManager.getLocalDB().getMongo();
    this._db = ns.substring(0, ns.indexOf("."));
    this._collection = ns.substring(ns.indexOf(".")+1);
    this._namespace = ns;

    this.reset();
}

IndexStatsAccumulator.prototype.help = function() {
    print("IndexStatsAccumulator functions");
    print("\t.takeSnapshot() - captures index statistics at a point in time. " 
        + "Multiple snapshots used to generate statistics.");
    print("\t.getLastDiff() - "
        + "Provides aggregate statistics collected between the last 2 snapshots.");
    print("\t.getTotalCollected() - " 
        + "Provides aggregate statistics collected between the first and last snapshot.");
    print("\t.reset() - Removes all stored snapshot data, resetting this accumulator");
    
}

/**
 * Clears IndexStatsAccumulator state.
 */
IndexStatsAccumulator.prototype.reset = function() {

    // Snapshot times used to report coverage times.
    this._snapshotTimeFirst = null;
    this._snapshotTimeSecondToLast = null;
    this._snapshotTimeLast = null;

    this._numSnapshots = 0;

    // Holds last snapshot for each index/server pair.
    this._baseline = new Map();
    // Holds the aggregate index usage count for each server between the last 2 snapshots.
    this._statsLastDiff = new Map();
    // Holds the aggregate index usage count for each server across all snapshots.
    this._statsCumulative = new Map();

    // Holds success/failure count for the $indexStats call to each server.
    this._serverRetrievalStatus = new Map();
}

/**
 * Retrieves current index statistics from all cluster members and adds to basline. If more than
 * one snapshot has been taken:
 * 1) A diff is taken between the last 2 snapshots to generate statstics for that time period.
 * 2) The running statistics totals are updated to reflect the last diff.
 */
IndexStatsAccumulator.prototype.takeSnapshot = function() {
    var serverList = this._getServerList(this._mongo);
    var statsArray = [];

    for (var jj = 0; jj < serverList.length; ++jj) {
        try {
            var conn = this._connectionManager.getConnection(serverList[jj]);
            var db = conn.getDB(this._db);
            db.getMongo().setSlaveOk(true);
            
            var stats = 
                db.getCollection(this._collection).aggregate([{$indexStats: {}}]).toArray();
            assert(stats.length > 0, "No results found. It is likely that the namepace provided is not valid.");

            statsArray = statsArray.concat(stats);
            this._recordServerRetrievalStatus(serverList[jj], true);
        }
        catch (err) {
            this._recordServerRetrievalStatus(serverList[jj], false, err);
        }
    }

    this._buildLastDiff(statsArray);
    this._updateCumulativeStats();
    this._updateBaseline(statsArray);

    if (this._snapshotTimeFirst === null) {
        this._snapshotTimeFirst = new Date();
        this._snapshotTimeLast = this._snapshotTimeFirst;
    }
    else {
        this._snapshotTimeSecondToLast = this._snapshotTimeLast;
        this._snapshotTimeLast = new Date();
    }

    this._numSnapshots++;
    return;
}

/**
 * Returns statistics gathered between the last 2 snapshots.
 */
IndexStatsAccumulator.prototype.getLastDiff = function() {
    return this._buildResultDoc(this._statsLastDiff,
                                this._snapshotTimeSecondToLast,
                                this._snapshotTimeLast);
}

/**
 * Returns the cumulative statistics gathered between all snapshot pairs.
 */
IndexStatsAccumulator.prototype.getTotalCollected = function() {
    var doc = this._buildResultDoc(this._statsCumulative,
                                   this._snapshotTimeFirst,
                                   this._snapshotTimeLast);
    doc.exceptions = this._getServerRetrievalExceptions();

    return doc;
}

/**
 * Builds a list of mongoD instances where we had incomplete snapshot coverage. Provides %
 * available with each.
 */
IndexStatsAccumulator.prototype._getServerRetrievalExceptions = function() {
    var exceptionList = [];
    var values = this._serverRetrievalStatus.values();
    for (var kk = 0; kk < values.length; ++kk) {
        var serverDoc = values[kk];
        if (serverDoc.fail > 0) {
            var availablePct 
                =  Math.floor((serverDoc.success / (serverDoc.fail + serverDoc.success)) * 100);
            var exceptionDoc = {"host": serverDoc.host, "availablePct": availablePct};
            exceptionList.push(exceptionDoc);
        }
    }

    return exceptionList;
}

/**
 * Records whether a snapshot retrieval attempt was successful for a given server.
 */
IndexStatsAccumulator.prototype._recordServerRetrievalStatus = function(host, 
                                                                        success, 
                                                                        optionalError) {
    var entry = this._serverRetrievalStatus.get(host);

    if (!entry) {
        entry = {host: host, success: 0, fail: 0};
    }

    if (success) {
        entry.success++;
    }
    else {
        entry.fail++;
    }

    this._serverRetrievalStatus.put(host, entry);

    if (optionalError) {
        print(optionalError);
    }
}

/**
 * Retrieve a list of all servers hosting data for a given collection. This includes all shard /
 *  replica set members regardless of replica state.
 */
IndexStatsAccumulator.prototype._getServerList = function(conn) {
    var list = [];

    var isMaster = conn.getDB('admin').isMaster();

    if (isMaster.msg == 'isdbgrid') { // mongos
        var stats = conn.getDB(this._db).getCollection(this._collection).stats();

        var shards = [];
        if (stats.sharded) {
            for (var shardName in stats.shards) {
                shards.push(shardName);
            }
        }
        else {
            shards.push(stats.primary);
        }

        list = list.concat(this._getShardMembers(shards));
    }
    else if (isMaster.setName) { // mongoD replica set
        var members = this._getReplicaSetMembers(conn);
        list = list.concat(members);
    }
    else { // standalone
        list.push(conn.host);
    }

    return list;
}

/**
 * Returns the address of all replica members for the members of shardList.
 */
IndexStatsAccumulator.prototype._getShardMembers = function(shardList) {
    var members = [];

    var config = this._mongo.getDB("config");

    for (var shard in shardList) {
        var shardDoc = config.shards.findOne({_id: shardList[shard]});
        var conn = this._connectionManager.getConnection(shardDoc.host);
        members = members.concat(this._getServerList(conn));
    }

    return members;
}

/**
 * Returns the address of all members for a given replica set.
 */
IndexStatsAccumulator.prototype._getReplicaSetMembers = function(conn) {
    var members = [];

    var resp = conn.getDB("admin")._adminCommand({replSetGetConfig:1});
    var config = null;

    if (resp.ok && !(resp.errmsg) && resp.config) {
        config = resp.config;
    }
    else if (resp.errmsg && resp.errmsg.startsWith("no such cmd")) {
        config = conn.getDB("local").system.replset.findOne();
    }

    if (!config) {
        throw new Error("Could not retrieve replica set config: " + tojson(resp));
    }

    for (var index in config.members) {
        members.push(config.members[index].host);
    }

    return members;
}

/**
 * Generates statistics for the period captured between the last 2 snapshots.
 */
IndexStatsAccumulator.prototype._buildLastDiff = function(statsArr) {
    var diffMap = new Map();

    for (var jj = 0; jj < statsArr.length; ++jj) {
        var statsRecord = statsArr[jj];
        var baselineRecord = this._baseline.get({p: statsRecord.host, i: statsRecord.key});

        // To generate statistics we need a previous baseline to diff against and that baseline has
        // to be valid (checked by comparing since timestamp). A baseline can be invalidated
        // By mongod restart or index removal and addition.
        // We will only include operations when we have 2 consecutive snapshots. We could miss valid
        // data on doing so, but this removes potential unknowns like non-cluster queries run against a
        // replica that was removed from a replica set. It also makes error reporting easier to track
        // and understand (reporting missed snapshot intervals rather than trying to piece together
        // missing time intervals).
        if (baselineRecord
            && baselineRecord.presentInLastSnapshot
            && (statsRecord.accesses.since.getUTCSeconds()
                == baselineRecord.accesses.since.getUTCSeconds()) 
            &&  (statsRecord.accesses.ops >= baselineRecord.accesses.ops)) {

            var ops = statsRecord.accesses.ops - baselineRecord.accesses.ops;
            var diffEntry = diffMap.get({i: statsRecord.key});

            if (!diffEntry) {
                diffEntry = {name: statsRecord.name, key: statsRecord.key, accesses: {ops: 0}};
                diffEntry.servers = new Map();
            }

            diffEntry.accesses.ops += ops;
            diffEntry.servers.put(statsRecord.host, statsRecord.host);
            diffMap.put({i: statsRecord.key}, diffEntry);
        }
    }

    this._statsLastDiff = diffMap;
}

/**
 * Updates the current statistics baseline. This provides us with both the last counter value for
 * each process/index pair as well as the date/time that reading is valid from.
 */
IndexStatsAccumulator.prototype._updateBaseline = function(statsArr) {
    var baselineValues = this._baseline.values();
    for (var kk = 0; kk < baselineValues.length; ++kk) {
        if (baselineValues[kk]) {
            baselineValues[kk].presentInLastSnapshot = false;
        }
    }

    for (var jj = 0; jj < statsArr.length; ++jj) {
        var newEntry = statsArr[jj];
        newEntry.presentInLastSnapshot = true;
        this._baseline.put({p: newEntry.host, i: newEntry.key}, newEntry);
    }
}

/**
 * Update our running statistics total with the last diff captured.
 */
IndexStatsAccumulator.prototype._updateCumulativeStats = function() {
    var lasDiffList = this._statsLastDiff.values();
    for (var jj = 0; jj < lasDiffList.length; ++jj) {
        var lastDiff = lasDiffList[jj];
        var cumulativeEntry = this._statsCumulative.get({i: lastDiff.key});
        if (!cumulativeEntry) {
            cumulativeEntry = {name: lastDiff.name, key: lastDiff.key, accesses: {ops: 0}};
            cumulativeEntry.servers = new Map();
            this._statsCumulative.put({i: lastDiff.key}, cumulativeEntry);
        }
        cumulativeEntry.accesses.ops += lastDiff.accesses.ops;

        var serverList = lastDiff.servers.values();
        for (var kk =  0; kk < serverList.length; ++kk) {
            cumulativeEntry.servers.put(serverList[kk], serverList[kk]);
        }
    }
}

/**
 * Generates the user facing statistics document returned by the getLastDiff and getTotalCollected
 * functions.
 */
IndexStatsAccumulator.prototype._buildResultDoc = function(resultMap, startTime, endTime) {

    if (this._numSnapshots < 2) {
        throw Error("At least 2 snapshots needed to generate statistics.");
    }

    var doc = {};
    doc.startTime = startTime;
    doc.endTime = endTime;
    doc.hosts = [];
    doc.indexes = [];

    var mongodMap = new Map();
    var values = resultMap.values();
    for (var jj = 0; jj < values.length; ++jj) {
        var entry = values[jj];
        var indexDoc = {name: entry.name, key: entry.key, accesses: entry.accesses};
        doc.indexes.push(indexDoc);

        var entryMongodList = entry.servers.values();
        for (var kk =  0; kk < entryMongodList.length; ++kk) {
            mongodMap.put(entryMongodList[kk], entryMongodList[kk]);
        }
    }

    doc.hosts = mongodMap.values();
    return doc;
}


var IndexAccessStats = {
    connectionManager: new ConnectionManager(db),
    showStatus: true,
    setAuth: function(user,pwd) {
        this.connectionManager.setAuth(user, pwd);
    },
    setQuietMode: function() {
        this.showStatus = false;
    },
    collect: function(namespace, durationInMinutes) {

        if (undefined === durationInMinutes) {
            throw new Error("durationInMinutes must be defined for collect.");
        }

        if (durationInMinutes < 1 || durationInMinutes !== parseInt(durationInMinutes, 10)) {
            throw new Error("durationInMinutes must be a positive integer value for collect.");
        }

        var minutesText = " minute";
        if (durationInMinutes > 1) {
            minutesText += "s";
        }

        if (this.showStatus) {
            print("");
            print("Capturing index usage statistics. This script will run for "
                + durationInMinutes + minutesText + ".");
            print("");
        }

        var oneMinuteInMs = 60000;
        var acc = new IndexStatsAccumulator(this.connectionManager, namespace);
        var start = new Date();
        var end = new Date(start.getTime() + (durationInMinutes * oneMinuteInMs));

        var count = 1;
        do {
            if (this.showStatus) {
                print("Taking snapshot " + count++ + " (and sleeping for one minute)");
            }
            acc.takeSnapshot();
            sleep(oneMinuteInMs);
        }
        while (Date.now() < end);

        // Take a final snapshot to make sure we have covered at least duration given.
        if (this.showStatus) {
            print("Taking final snapshot");
            print("");
        }
        acc.takeSnapshot();

        return acc.getTotalCollected();
    },
    help: function() {
        print("");
        print("// Index usage statistics will be collected at a 1 minute granularity for");
        print("// the specified duration")
        print("********************************************************************************");
        print("**** Usage:                                                                 ****");
        print("********************************************************************************");
        print("");
        print("// Set credentials for user with ClusterMonitor role (if using auth)");
        print("// If running against an auth-enabled sharded cluster ClusterMonitor must")
        print("// be setup both at the mongoS level and for each shard. This is the same")
        print("// setup required by CloudManager and OpsManager.")
        print("IndexAccessStats.setAuth(userName, password);");
        print("");
        print("// Collect index usage for specified collection and duration. A document");
        print("// with aggregated results will be returned by this method.")
        print("IndexAccessStats.collect(\"database.collection\", collectionTimeInMinutes);");
        print("");
        print("// Set quiet mode for scripted execution. Will suppress status messages.");
        print("IndexAccessStats.setQuietMode();");
        print("");
        print("********************************************************************************");
        print("**** Example:                                                               ****");
        print("********************************************************************************");
        print("");
        print("To collect and print access statistics for the foo.bar collection,");
        print("for a period of one hour:");
        print("");
        print("> var oneHourInMinutes = 60;");
        print("> var namespace = \"foo.bar\";");
        print("> IndexAccessStats.collect(namespace, oneHourInMinutes)");
        print("{");
        print("    \"startTime\" : ISODate(\"2015-10-09T14:46:53.641Z\"),");
        print("    \"endTime\" : ISODate(\"2015-10-09T15:46:53.656Z\"),");
        print("    \"hosts\" : [");
        print("        \"foo.local:27017\"");
        print("    ],");
        print("    \"indexes\" : [");
        print("        {");
        print("            \"name\" : \"a_1\",");
        print("            \"key\" : {");
        print("                \"a\" : 1");
        print("            },");
        print("           \"accesses\" : {");
        print("                \"ops\" : 123");
        print("            }");
        print("        },");
        print("        {");
        print("            \"name\" : \"_id_\",");
        print("            \"key\" : {");
        print("                \"_id\" : 1");
        print("            },");
        print("            \"accesses\" : {");
        print("                \"ops\" : 37888");
        print("            }");
        print("       }");
        print("    ],");
        print("    \"exceptions\" : [ ]");
        print("}");
        print("");
    }
}

print("");
print("********************************************************************************");
print("***                                                                          ***");
print("***                    Loaded indexStats.js                                  ***");
print("***                                                                          ***");
print("*** Warning:                                                                 ***");
print("***  Index access statistics can be used to help understand collection index ***");
print("***  usage. It should not be used as the sole means for determining whether  ***");
print("***  an index can/should be dropped. Please use these results as a starting  ***");
print("***  point for a more thorough investigation. Please test any changes to     ***");
print("***  validate.                                                               ***");
print("***                                                                          ***");
print("*** IndexAccessStats.help() - for details                                    ***");
print("***                                                                          ***");
print("********************************************************************************");
print("");

