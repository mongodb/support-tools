/*
=================================================
dbcheck.js: MongoDB guided dbCheck remediation
=================================================

Copyright MongoDB, Inc, 2022

Use this script as part of the guidance in
https://github.com/mongodb/support-tools/tree/replset-consistency/replset-consistency/README.md

Usage:
  mongosh mongodb://127.0.0.1:27017/?replicaSet=replset dbcheck.js 2>&1 | tee
  dbcheckresults.json
 or
  mongo mongodb://127.0.0.1:27017/?replicaSet=replset dbcheck.js 2>&1 | tee
  dbcheckresults.json

 Partial results can be found by passing --eval
   To run on a specific list of name spaces.
    --eval "ns = ['admin.system.version','config.system.sessions']"
   To run on a specific list of databases
    --eval "dbs = ['admin']"
   Combination of databases and namespaces
    --eval "dbs = ['admin']; ns =
    ['admin.system.version','config.system.sessions']"

 This must be run as a user with the following roles:
   - listDatabases: List all databases
   - listCollections: List all collections on all databases
   - applyOps: needed for dbCheck
   - serverStatus: Collect the node's uptime
   - dbCheck: run the dbcheck command
 Default roles that include these permissions are __system and root
 The following is a custom role that should allow this script to run.
db.adminCommand({
  createRole: "remediationAdmin",
  roles: [ "clusterManager", "clusterMonitor", "readWriteAnyDatabase"],
  privileges: [
    { resource: {cluster: true},
      actions: ["applyOps", "listDatabases", "serverStatus"] },
    { resource: {db: "local", collection: "system.healthlog"},
      actions: ["find"] },
    { resource: {db: "__corruption_repair", collection: "unhealthyRanges"},
      actions: ["find", "insert", "update", "remove", "createCollection",
      "dropCollection", "createIndex", "dropIndex"]
    },
    { resource: { anyResource: true }, actions: [
     "listCollections", "validate" ]},
  ]
});

Last line examples:
Success:
 {"dbCheckOk":true,"rollOver":false,"healthlogRolloverPrimary":false,"healthlogRolloverSecondary":false,"primaryStartCount":7,"secondaryStartCount":35,"writeConcern":3,"timeout":1000,"partial":false,"host":"localhost:27017","setName":"replset","time":{"$date":"2022-01-27T23:28:39.920Z"},"runCount":7,"okCount":7,"notOkCount":0,"notOk":[],"lastStartup":{"$date":"2022-01-27T22:25:17.020Z"},"dbCheckDurationSecs":0.048}
Rollover:
 {"dbCheckOk":true,"rollOver":true,"healthlogRolloverPrimary":true,"healthlogRolloverSecondary":false,"primaryStartCount":4,"secondaryStartCount":42,"writeConcern":3,"timeout":1000,"partial":false,"host":"localhost:27017","setName":"replset","time":{"$date":"2022-01-27T23:29:23.496Z"},"runCount":7,"okCount":7,"notOkCount":0,"notOk":[],"lastStartup":{"$date":"2022-01-27T22:25:17.020Z"},"dbCheckDurationSecs":0.064}

If collections are deleted the script may exit prematurely. Collections added
may not be checked. Running against a primary without the replica set
parameter may cause errant rollover results.

Manually check if the healthlog has rolled over on each secondary. The
following shell example can be compared against runcount to determine
rollover status.

db.getSiblingDB("local").system.healthlog.aggregate([
  { $match: { operation: "dbCheckStart" } },
  { $count: "dbCheckStartCount" }
 ]);

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


const wtimeout = 1000;     // Recommended wtimeout
const pollinterval = 1000; // 1 second

if (typeof EJSON !== 'undefined') {
  db.getMongo().setReadPref("primaryPreferred");
} else {
  if (typeof rs.secondaryOk == 'function') {
    rs.secondaryOk();
  } else {
    rs.slaveOk();
  }
}

function printFunction(toprint) {
  if (typeof EJSON !== 'undefined') {
    print(EJSON.stringify(toprint));
  } else {
    print(tojson(toprint, "", true));
  }
}

var runCount = 0;
var okCount = 0;
var failArray = [];
var seen = [];
var partial = false;
var writeConcern = 0;
var primaryCount = 0;
var secondaryCount = 0;

// clusterMonitor or clusterManager for replSetGetConfig
// The user could pass in a write concern, but we have to assume we need to
// calculate it. Note: If there are non-eligible secondaries, they won't be used
// to verify the primary.
function getWriteConcern() {
  // Filter out arbiters, hidden, and non-eligible secondaries.
  if (writeConcern == 0) {
    writeConcern =
        rs.conf()
            .members
            .filter(x => {return x.hidden == false && x.priority > 0 &&
                                 x.votes > 0 && x.arbiterOnly == false})
            .length;
  }
  return writeConcern;
}

function getDBCheckCount(readPref) {
  if (readPref == null) {
    readPref = "primary";
  }
  db.getMongo().setReadPref(readPref);

  let curr = db.getSiblingDB("local").system.healthlog.aggregate([
    {$match : {operation : "dbCheckStart"}}, {$count : "dbCheckStartCount"}
  ]);
  if (curr.hasNext()) {
    let my_count = curr.next().dbCheckStartCount;
    return my_count;
  }
  return 0;
}

function getDBCheckCountByNode(node) {
  let conn = node.connection
  let curr = conn.getDB("local").getCollection("system.healthlog").aggregate([     
    {$match : {operation : "dbCheckStart"}}, {$count : "dbCheckStartCount"}   
  ])
  if (curr.hasNext()) {
    let my_count = curr.next().dbCheckStartCount;
    node.dbCheckStartCount = my_count
    return my_count
  }
  return 0;
}

// Non-deterministic, we don't know if we'll select the same secondary over and
// over again.
//
function checkRollOver() {
  let config = rs.config();
  let nodelist = [];

  uriOptions = authInfo.uriOptions;
  delete authInfo.uriOptions;
  
  try {
    primaryCount = getDBCheckCount("primary")
  } catch (error) {
    printFunction(error);
  }
  
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
  
  for (let i = 0; i < nodelist.length; i++) {
    try {   
      let tcount = getDBCheckCountByNode(nodeInfo)
      if (i == 0) {
        secondaryCount = tcount;
      } else {
        secondaryCount = Math.min(secondaryCount, tcount);
      }
    } catch (error) {
      printFunction(error);
    }
  }
}

function getLastDoc() {
  let arr = db.getSiblingDB("local")
                .system.healthlog.find({})
                .sort({timestamp : -1})
                .limit(1)
                .toArray();
  if (arr.length == 0) {
    return null;
  } else {
    return arr[0];
  }
}

/* Polls the primary healthlog every second for the last document, if it's a
 * dbCheckStop and later than our starting doc, our command finished. */
function waitForStop(base) {
  let filter = {operation : "dbCheckStop"};
  if (base != null) {
    filter["timestamp"] = { $gte : base }
  }
  while (true) {
    // printFunction({ DEBUG: 1, base: base });
    let curr = db.getSiblingDB("local")
                   .system.healthlog.find({})
                   .sort({$natural : -1})
                   .limit(1)
                   .maxTimeMS(pollinterval);
    if (curr.hasNext()) {
      let doc = curr.next();
      // printFunction({ DEBUG: 1, doc: doc });
      if ("operation" in doc) {
        if (doc.operation === "dbCheckStop") {
          if (base == null) {
            return doc;
          }
          if (doc.timestamp > base.timestamp) {
            return doc;
          }
        }
      }
    }
    sleep(pollinterval);
  }
}

var currentBase = null;
function dbCheckCollection(d, coll) {
  let checkresults = {"ok" : false};
  if (partial) {
    if (seen.includes("db:" + d + ", coll: " + coll)) {
      return;
    }
  }

  if (currentBase == null) {
    currentBase = getLastDoc();
  }

  var timerStart = new Date();
  // This is a one shot, we may get back something other thank ok: true if there
  // is a failure...
  checkresults = db.getSiblingDB(d).runCommand({
    "dbCheck" : coll,
    "batchWriteConcern" : {"w" : getWriteConcern(), "wtimeout" : wtimeout}
  });

  if (checkresults.ok == undefined) {
    printFunction({
      "msg" : "missing ok field in validate output",
      "db" : d,
      "coll" : coll
    });
  } else {
    runCount++;
    if (checkresults.ok) {
      okCount++;
    } else {
      failArray.push({database : d, collection : coll, results : checkresults})
    }
  }

  currentBase = waitForStop(currentBase);
  var timerEnd = new Date();

  printFunction({
    database : d,
    collection : coll,
    dbCheckDurationSecs : (timerEnd - timerStart) / 1000,
    results : checkresults
  });
  if (partial) {
    seen.push("db:" + d + ", coll: " + coll);
  }
}

function collectionNameFilter(name) {
  if (((name.startsWith("dbcheck.") || name.startsWith("dbcheck_backup.")) &&
       name.match(/[.][0-9]+$/).length == 1)) {
    return false;
  }
  if (name === "system.profile") {
    return false;
  }
  return true;
}

function gci(d) {
  return db.getSiblingDB(d)
      .getCollectionInfos({type : "collection"}, true)
      .map(function(infoObj) { return infoObj.name; })
      .filter(name => collectionNameFilter(name));
}

var paritalNames = {};
function getCollectionNames(d) {
  if (partial) {
    if (paritalNames[d] !== undefined) {
      return paritalNames[d];
    }
    paritalNames[d] = gci(d);
    return paritalNames[d];
  }
  return gci(d);
}

function checkDatabase(d) {
  getCollectionNames(d).forEach(function(coll) {
    if (d == "local") {
      return;
    }
    dbCheckCollection(d, coll);
  });
}

var timerStart = new Date();

if (typeof dbs == 'object') {
  partial = true;
  dbs.forEach(function(d) { checkDatabase(d); });
}
if (typeof ns == 'object') {
  partial = true;
  ns.forEach(function(n) {
    if (n.indexOf('.') == -1) {
      return;
    }
    var d = n.substring(0, n.indexOf("."))
    var coll = n.substring(n.indexOf(".") + 1, n.length);
    if (getCollectionNames(d).includes(coll)) {
      dbCheckCollection(d, coll);
    }
  });
}

if (!partial) {
  db.getMongo()
      .getDBNames({readPreference : 'primaryPreferred'})
      .forEach(function(d) { checkDatabase(d); });
}

var timerEnd = new Date();
var helloDoc = (typeof db.hello !== 'function') ? db.isMaster() : db.hello();
var lastStartup = new Date(new Date() - db.serverStatus().uptimeMillis);
sleep(1000); // Not sure this is necessary, but sometimes dbCheck results can
             // appear shortly after the command returns ok.

authInfo.db = authInfo.db || 'local';
checkRollOver();
printFunction({
  dbCheckOk : failArray.length == 0,
  rollOver : !(primaryCount >= runCount) || !(secondaryCount >= runCount),
  healthlogRolloverPrimary : !(primaryCount >= runCount),
  healthlogRolloverSecondary : !(secondaryCount >= runCount),
  primaryStartCount : primaryCount,
  secondaryStartCount : secondaryCount,
  writeConcern : getWriteConcern(),
  timeout : wtimeout,
  partial : partial,
  host : helloDoc.me,
  setName : helloDoc.setName,
  time : new Date(),
  runCount : runCount,
  okCount : okCount,
  notOkCount : failArray.length,
  notOk : failArray,
  lastStartup : lastStartup,
  dbCheckDurationSecs : (timerEnd - timerStart) / 1000
});
