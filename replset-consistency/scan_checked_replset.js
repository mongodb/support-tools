/*
=================================================
scan_checked_replset.js: MongoDB guided dbCheck remediation
=================================================

Copyright MongoDB, Inc, 2022

Use this script as part of the guidance in
https://github.com/mongodb/support-tools/tree/replset-consistency/replset-consistency/README.md

scan_checked_replset collects bad ranges (as reported by dbCheck) from each node in a
replica set to a replicated collection, and collects the documents from those ranges into
a set of collections.

Run dbCheck before running this script.
Any inconsistent documents are stored in collections named
 <dbname>.dbcheck_backup.<collname>.<node_id>
Inconsistent documents and metadata about missing documents are also stored in collections named:
 <dbname>.dbcheck.<collname>.<node_id>

Usage:
mongo --host <primaryHostAndPort> --eval "authInfo={<auth object>}" \
 scan_checked_replset.js

The user specified by authInfo needs to be extremely privileged: it needs to be able to read and
write any database, have the applyOps privilege, read 'local.system.healthlog', and read and
write '__corruption_repair.unhealthyRanges' (which may be dropped when the repair is complete)

For instance, this role works if only user collections are damaged:
createRole(
     {role: "corruptAdmin", roles: [ "clusterMonitor", "readWriteAnyDatabase"],
       privileges: [{resource: {cluster: true}, actions: ["applyOps"]},
                    {resource: {db: "local", collection: "system.healthlog"},
                     actions: ["find"]},
                    {resource: {db: "__corruption_repair", collection: "unhealthyRanges"},
                     actions: ["find", "insert", "update", "remove", "createCollection",
                      "dropCollection", "createIndex", "dropIndex"]}]});

If system collections are damaged, additional privileges to read and write them are needed.

Additional authentication and URI options may be specified in the authInfo object:

mongo --host <primaryHostAndPort> --tls --tlsCAFile=path/to/ca.pem \
      --eval 'authInfo={user:"remediate", pwd:"password", mechanism: "PLAIN", db: "$external" uriOptions: "tls=true&tlsCAFile=path/to/ca.pem"}' \
      scan_checked_replset.js | tee scan.txt_{{date +"%Y-%m-%d_%H-%M-%S"}}

Please note: all tools/ scripts in this repo are released for use "AS
IS" without any warranties of any kind, including, but not limited to
their installation, use, or performance. We disclaim any and all
warranties, either express or implied, including but not limited to
any warranty of noninfringement, merchantability, and/ or fitness for
a particular purpose. We do not warrant that the technology will
meet your requirements, that the operation thereof will be
uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is at your own risk. There is no
guarantee that they have been through thorough testing in a
comparable environment and we are not responsible for any damage
or data loss incurred with their use.

You are responsible for reviewing and testing any scripts you run
thoroughly before use in any non-testing environment.

LICENSE

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License. */

const healthCollName = "system.healthlog";
const metadataDbName = "__corruption_repair";
const rangeCollName = "unhealthyRanges";
const saveCollPrefix = "dbcheck_";
const backupCollPrefix = "dbcheck_backup_";
var backup;

function getLeastId(docs) {
    let leastId = undefined;
    let leastIndices = [];
    for (let i = 0; i < docs.length; i++) {
        if (docs[i] !== undefined) {
            if (leastIndices.length == 0) {
                leastId = docs[i]._id;
                leastIndices = [i];
            } else {
                let order = bsonWoCompare(docs[i]._id, leastId);
                if (order == 0) {
                    leastIndices.push(i);
                } else if (order < 0) {
                    leastId = docs[i]._id;
                    leastIndices = [i];
                }
            }
        }
    }
    return [leastId, leastIndices];
}

function pickDoc(choices) {
    let candidates = [];
    // Goes through each possibility in "choices" and adds unique ones to "candidates".
    // This is O(N^2) when they are all different and O(N) when they are all the same, but
    // we expect N is small (number of nodes in the system) and they're usually all the same.
    for (let i = 0; i < choices.length; i++) {
        let j = 0;
        for (; j < candidates.length; j++) {
            if (choices[i] === undefined || candidates[j].doc === undefined) {
                if (choices[i] === undefined && candidates[j].doc === undefined) {
                    candidates[j].mult += 1;
                    break;
                }
            } else if (bsonWoCompare(candidates[j].doc, choices[i]) == 0) {
                candidates[j].mult += 1;
                break;
            }
        }
        if (j == candidates.length) {
            candidates.push({index: i, mult: 1, doc: choices[i]});
        }
    }
    if (candidates.length <= 1) {
        return ["consistent", choices.length];
    }
    candidates.sort((a, b) => {
        return b.mult - a.mult;
    });
    // If we don't have a plurality, no decision.
    if (candidates[0].mult == candidates[1].mult) {
        return [undefined, candidates[0].mult];
    }
    if (candidates[0].doc === undefined) {
        return ["delete", candidates[0].mult];
    }
    return [candidates[0].index, candidates[0].mult];
}

function getEarliestAppliedOpTime(dbToRepair) {
    db = dbToRepair;
    let status = rs.status();
    let minoptime;
    for (let member of status.members) {
        if (member.optime) {
            try {
                if (!minoptime || (rs.compareOpTimes(member.optime, minoptime) < 0))
                    minoptime = member.optime;
            } catch (e) {
                throw {reason: "Invalid Optime", member: member};
            }
        }
    }
    return minoptime;
}

function bestEffortKillSessions(sessionsToKill) {
    // Best-effort clean up of any resources left behind by failed attempts to open a snapshot.
    for (session of sessionsToKill) {
        try {
            session.getClient().adminCommand({killSessions: [session.getSessionId()]});
        } catch (e) {
        }
    }
}

function createNodeCursor(session, dbName, collName, filterExpr, clusterTime) {
    let findCommand;
    if (majorVersion < 5) {
        findCommand = {
            find: collName,
            filter: {_id: filterExpr},
            sort: {_id: 1},
            $_internalReadAtClusterTime: clusterTime
        };
    } else {
        findCommand = {
            find: collName,
            filter: {_id: filterExpr},
            sort: {_id: 1},
            readConcern: {level: "snapshot", atClusterTime: clusterTime}
        };
    }
    let repairNodeDb = session.getDatabase(dbName);
    let res = repairNodeDb.runCommand(findCommand);
    return new DBCommandCursor(repairNodeDb, res);
}

function establishRangeCursors(dbToRepair, nodelist, range, prevEndKey) {
    let cursors = [];
    let sessions = [];
    let sessionsToKill = [];
    let dbName = range._id.db;
    let collName = range._id.collection;
    let filterExpr;
    if (prevEndKey === undefined)
        filterExpr = {$gte: range._id.minKey, $lt: range._id.maxKey};
    else
        filterExpr = {$gt: prevEndKey, $lt: range._id.maxKey};
    while (cursors.length == 0) {
        let clusterTime = getEarliestAppliedOpTime(dbToRepair).ts;
        try {
            for (let nodeinfo of nodelist) {
                let conn = nodeinfo.connection;
                sessions.push(conn.startSession());
            }
            for (let session of sessions) {
                cursors.push(createNodeCursor(session, dbName, collName, filterExpr, clusterTime));
            }
        } catch (e) {
            if (e.code == ErrorCodes.SnapshotTooOld || e.code == ErrorCodes.SnapshotUnavailable) {
                print("Transient error: could not establish a common snapshot");
                for (session of sessions) {
                    sessionsToKill.push(session);
                }
                sessions = [];
                cursors = [];
                sleep(200);
            } else
                throw e;
        }
    }
    bestEffortKillSessions(sessionsToKill);
    return [sessions, cursors];
}

function getSaveCollectionName(range, nodeinfo) {
    return saveCollPrefix + range._id.collection + "." + nodeinfo._id;
}

function getBackupCollectionName(range, nodeinfo) {
    return backupCollPrefix + range._id.collection + "." + nodeinfo._id;
}

function repairRange(dbToRepair, nodelist, range) {
    printjson({msg: "Scanning range", range: range});
    let dbName = range._id.db;
    let collName = range._id.collection;
    let ids = [];
    let primaryDb = dbToRepair.getSiblingDB(dbName);
    let primaryColl = primaryDb[collName];
    let saveColls = [];
    let backupColls = [];
    let keyAtFailure = undefined;

    for (let nodeinfo of nodelist) {
        saveColls.push(primaryDb[getSaveCollectionName(range, nodeinfo)]);
        backupColls.push(primaryDb[getBackupCollectionName(range, nodeinfo)]);
    }

    do {
        let docs = [];
        let [sessions, cursors] = establishRangeCursors(dbToRepair, nodelist, range, keyAtFailure);
        keyAtFailure = undefined;
        for (let cursor of cursors) {
            if (cursor.hasNext()) {
                docs.push(cursor.next());
            } else {
                docs.push(undefined);
            }
        }

        let [leastId, leastIndices] = getLeastId(docs);
        // As long as we have at least one doc, keep going.
        while (leastIndices.length) {
            // The choices array is the same as the docs array, except it doesn't include (marks as
            // undefined) docs which don't have the same id as leastId.
            let choices = new Array(docs.length);
            for (let i of leastIndices) {
                choices[i] = docs[i];
            }
            let [decision, maxAgreeingNodes] = pickDoc(choices);
            if (decision != "consistent") {
                for (let i = 0; i < choices.length; i++) {
                    let saveDoc = choices[i];
                    if (saveDoc && backup) {
                        backupColls[i].replaceOne(
                            {_id: leastId}, saveDoc, {upsert: true, writeConcern: {w: 1}});
                    }
                    if (saveDoc === undefined) {
                        saveDoc = {_id: leastId, "dbcheck_docWasMissing": 1};
                    }
                    saveColls[i].replaceOne(
                        {_id: leastId}, saveDoc, {upsert: true, writeConcern: {w: 1}});
                }
            }
            try {
                // Advance all docs at minimum.
                for (let i of leastIndices) {
                    if (cursors[i].hasNext())
                        docs[i] = cursors[i].next();
                    else
                        docs[i] = undefined;
                }
            } catch (e) {
                if (e.code == ErrorCodes.SnapshotTooOld ||
                    e.code == ErrorCodes.SnapshotUnavailable) {
                    print("Transient error: Snapshot expired");
                    keyAtFailure = leastId;
                    break;  // Break out of while(leastindices.length);
                } else
                    throw e;
            }
            [leastId, leastIndices] = getLeastId(docs);
        }
        bestEffortKillSessions(sessions);
    } while (keyAtFailure !== undefined);
}

// Collects the bad ranges from all nodes into a replicated collection.  For convenience,
// returns the collection.
function findBadRanges(dbToRepair, nodelist) {
    let metadataDb = dbToRepair.getSiblingDB(metadataDbName);
    let rangeColl = metadataDb[rangeCollName];
    for (let nodeinfo of nodelist) {
        let conn = nodeinfo.connection;
        let localDb = conn.getDB("local");
        let cursor = localDb[healthCollName].find({severity: "error"});
        while (cursor.hasNext()) {
            let doc = cursor.next();
            if (doc.data && doc.data.success) {
                try {
                    let i = doc.namespace.indexOf(".");
                    let [dbName, collName] =
                        [doc.namespace.slice(0, i), doc.namespace.slice(i + 1)];
                    let res = rangeColl.insertOne({
                        _id: {
                            db: dbName,
                            collection: collName,
                            minKey: doc.data.minKey,
                            maxKey: doc.data.maxKey
                        }
                    },
                                                  {writeConcern: {w: 1}});
                } catch (e) {
                    if (e.code != ErrorCodes.DuplicateKey) {
                        throw e;
                    }
                    // Don't care about duplicate ranges.  Multiple secondaries may give the same
                    // range.
                }
            }
        }
    }
    return rangeColl;
}

function _repairDatabases(dbToRepair, authInfo, options) {
    db = dbToRepair;
    uriOptions = authInfo.uriOptions;
    delete authInfo.uriOptions;

    if (authInfo) {
        db.getMongo().auth(authInfo);
    }
    let config = rs.config();
    let nodelist = [];
    for (let member of config.members) {
        let conn = new Mongo("mongodb://" + member.host + "/?" + uriOptions);
        conn.setSecondaryOk(true);
        if (member.arbiterOnly) {
            conn.close();
        } else {
            if (authInfo) {
                conn.auth(authInfo);
            }
            nodelist.push({_id: member._id, connection: conn, host: member.host});
        }
    }
    let rangeColl = findBadRanges(dbToRepair, nodelist);
    let rangeCursor = rangeColl.find({scanned: {$ne: true}});
    while (rangeCursor.hasNext()) {
        let range = rangeCursor.next();
        repairRange(dbToRepair, nodelist, range, options);
        let saveCollNames = [];
        for (nodeinfo of nodelist) {
            saveCollNames.push(getSaveCollectionName(range, nodeinfo));
        }
        rangeColl.updateOne({_id: range._id},
                            {$set: {scanned: true, scanCollections: saveCollNames}});
    }
}

function repairDatabases(dbToRepair, authInfo, options) {
    try {
        _repairDatabases(dbToRepair, authInfo, options);
    } catch (e) {
        const preamble = "Remediation script failed";
        if (e.reason == "Invalid Optime") {
            print(`${preamble}: ${e.member.name} is in state ${
                e.member.stateStr}. Please make sure it's reachable as a primary or secondary.`);
            return;
        } else if (e.reason) {
            const errstr = "Error connecting to ";
            let startIndex = e.reason.indexOf(errstr);
            let endIndex = -1;
            if (startIndex >= 0) {
                startIndex += errstr.length;
                endIndex = e.reason.indexOf(" ::", startIndex);
            }
            if (startIndex <= 0) {
                const onhoststr = "on host '";
                startIndex = startIndex = e.reason.indexOf(errstr);
                if (startIndex >= 0) {
                    startIndex += hoststr.length;
                    endIndex = e.reason.indexOf("'", startIndex);
                }
            }
            if (endIndex >= 0) {
                let host = e.reason.slice(startIndex, endIndex);
                print(`${preamble}: The node ${host} is not available.  Please make sure all nodes in the replica set are up and in PRIMARY or SECONDARY states when running this script.`);
                return;
            }
        }
        throw e;
    }
}

var majorVersion = db.serverBuildInfo().versionArray[0];
var authInfo;
authInfo.db = authInfo.db || 'admin';
if (backup === undefined)
    backup = true;

if (typeof db.getMongo().auth === 'undefined' || typeof EJSON !== 'undefined' || typeof ErrorCodes === 'undefined') {
    print("")
    print("mongosh is not supported by this script. Please rerun this script using the legacy mongo shell.")
    print("")
} else {
    repairDatabases(db, authInfo);
}
