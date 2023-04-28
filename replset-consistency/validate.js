/*
=================================================
validate.js: MongoDB guided dbCheck remediation
=================================================

Copyright MongoDB, Inc, 2022

Use this script as part of the guidance in
https://github.com/mongodb/support-tools/tree/replset-consistency/replset-consistency/README.md

Usage:
  mongosh 127.0.0.1:27018 validate.js 2>&1 | tee results.json
 or
  mongo 127.0.0.1:27018 validate.js 2>&1 | tee results.json

 Partial results can be found by passing --eval
   To run on a specific list of name spaces.
    --eval "ns = ['admin.system.version','config.system.sessions']"
   To run on a specific list of databases
    --eval "dbs = ['admin']"
   Combination of databases and namespaces
    --eval "dbs = ['admin']; ns =
    ['admin.system.version','config.system.sessions']"

 To run with { full: true } 
    --eval "validateFull=true"

 This must be run as a user with the following roles:
   - listDatabases: List all databases
   - listCollections: List all collections on all databases
   - validate: Validate all collections (including system collections)
   - serverStatus: Collect the node's uptime
 Default roles that include these permissions are __system and root
 The following is a custom role that should allow this script to run.
 {
   role: "validateRole",
   privileges: [
     { resource: { cluster: true }, actions: [ "listDatabases",
     "serverStatus" ] }, { resource: { anyResource: true }, actions: [
     "listCollections", "validate" ] },
   ],
   roles: []
 }

Last line passed example:
 {"validation":"passed","valid":true,"passing":12,"failing":0,"failingNS":[],"partial":false,"host":"localhost:27018","setName":"replset","time":{"$date":"2021-11-15T22:54:11.341Z"},"lastStartup":{"$date":"2021-11-15T22:53:59.057Z"},"validateDurationSecs":1.567}
Last line failed example:
 {"validation":"failed","valid":false,"passing":11,"failing":1,"failingNS":[{"db":"status","coll":"status"}],"partial":false,"host":"localhost:27019","setName":"replset","time":{"$date":"2021-11-15T22:53:18.266Z"},"lastStartup":{"$date":"2021-11-15T22:52:31.835Z"},"validateDurationSecs":5.942}

If collections are deleted the script may exit prematurely. Collections added
may not be checked.

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

var allClean = true;
var passedCount = 0;
var failedCount = 0;
var failArray = [];
var seen = [];
var partial = false;

function validateCollection(d, coll, validateFull) {
    var validate_results = {"valid": false};
    if (partial) {
        if (seen.includes("db:" + d + ", coll: " + coll)) {
            return;
        }
    }
    validate_results = db.getSiblingDB(d).runCommand({validate: coll, full: validateFull});
    if (validate_results.valid == undefined) {
        printFunction({"msg": "missing valid field in validate output", "db": d, "coll": coll});
    }
    printFunction(validate_results);
    allClean = allClean && (validate_results.valid == true);
    if (validate_results.valid) {
        passedCount++;
    } else {
        failedCount++;
        failArray.push({"db": d, "coll": coll});
    }
    if (partial) {
        seen.push("db:" + d + ", coll: " + coll);
    }
}

var paritalNames = {};
function getCollectionNames(d) {
    if (partial) {
        if (paritalNames[d] !== undefined) {
            return paritalNames[d];
        }
        paritalNames[d] = db.getSiblingDB(d)
                              .getCollectionInfos({type: "collection"}, true)
                              .map(function(infoObj) {
                                  return infoObj.name;
                              });
        return paritalNames[d];
    }
    return db.getSiblingDB(d).getCollectionInfos({type: "collection"}, true).map(function(infoObj) {
        return infoObj.name;
    });
}

function validateDatabase(d, validateFull) {
    getCollectionNames(d).forEach(function(coll) {
        if (d == "local") {
            if (db.getSiblingDB(d).getCollection(coll).getFullName() == "local.oplog.rs") {
                return;
            }
        }
        validateCollection(d, coll, validateFull);
    });
}

var timerStart = new Date();

if (typeof validateFull == 'undefined' || validateFull != true) {
    validateFull = false;
}
if (typeof dbs == 'object') {
    partial = true;
    dbs.forEach(function(d) {
        validateDatabase(d, validateFull);
    });
}
if (typeof ns == 'object') {
    partial = true;
    ns.forEach(function(n) {
        if (n.indexOf('.') == -1) {
            return;
        }
        var d = n.substring(0, n.indexOf("."));
        var coll = n.substring(n.indexOf(".") + 1, n.length);
        if (getCollectionNames(d).includes(coll)) {
            validateCollection(d, coll, validateFull);
        }
    });
}

if (!partial) {
    db.getMongo().getDBNames({readPreference: 'primaryPreferred'}).forEach(function(d) {
        validateDatabase(d, validateFull);
    });
}

var timerEnd = new Date();
var helloDoc = (typeof db.hello !== 'function') ? db.isMaster() : db.hello();
printFunction({
    validation: (allClean ? "passed" : "failed"),
    valid: allClean,
    full: validateFull,
    passing: passedCount,
    failing: failedCount,
    failingNS: failArray,
    partial: partial,
    host: helloDoc.me,
    setName: helloDoc.setName,
    time: new Date(),
    lastStartup: new Date(new Date() - db.serverStatus().uptimeMillis),
    validateDurationSecs: (timerEnd - timerStart) / 1000
});
