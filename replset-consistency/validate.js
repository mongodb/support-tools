// Usage:
//   mongosh 127.0.0.1:27018 validate.js 2>&1 | tee results.json
//  or
//   mongo 127.0.0.1:27018 validate.js 2>&1 | tee results.json
//
//  Partial results can be found by passing --eval
//    To run on a specific list of name spaces.
//     --eval "ns = ['admin.system.version','config.system.sessions']"
//    To run on a specific list of databases
//     --eval "dbs = ['admin']"
//    Combination of databases and namespaces
//     --eval "dbs = ['admin']; ns =
//     ['admin.system.version','config.system.sessions']"
//
//
//  This must be run as a user with the following roles:
//    - listDatabases: List all databases
//    - listCollections: List all collections on all databases
//    - validate: Validate all collections (including system collections)
//    - serverStatus: Collect the node's uptime
//  Default roles that include these permissions are __system and root
//  The following is a custom role that should allow this script to run.
//  {
//    role: "validateRole",
//    privileges: [
//      { resource: { cluster: true }, actions: [ "listDatabases",
//      "serverStatus" ] }, { resource: { anyResource: true }, actions: [
//      "listCollections", "validate" ] },
//    ],
//    roles: []
//  }
//
//
// Last line passed example:
//  {"validation":"passed","valid":true,"passing":12,"failing":0,"failingNS":[],"partial":false,"host":"localhost:27018","setName":"replset","time":{"$date":"2021-11-15T22:54:11.341Z"},"lastStartup":{"$date":"2021-11-15T22:53:59.057Z"},"validateDurationSecs":1.567}
// Last line failed example:
//  {"validation":"failed","valid":false,"passing":11,"failing":1,"failingNS":[{"db":"status","coll":"status"}],"partial":false,"host":"localhost:27019","setName":"replset","time":{"$date":"2021-11-15T22:53:18.266Z"},"lastStartup":{"$date":"2021-11-15T22:52:31.835Z"},"validateDurationSecs":5.942}
//
// If collections are deleted the script may exit prematurely. Collections added
// may not be checked.

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

function validateCollection(d, coll) {
    var validate_results = {"valid": false};
    if (partial) {
        if (seen.includes("db:" + d + ", coll: " + coll)) {
            return;
        }
    }
    validate_results = db.getSiblingDB(d).runCommand({validate: coll});
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

function validateDatabase(d) {
    getCollectionNames(d).forEach(function(coll) {
        if (d == "local") {
            if (db.getSiblingDB(d).getCollection(coll).getFullName() == "local.oplog.rs") {
                return;
            }
        }
        validateCollection(d, coll);
    });
}

var timerStart = new Date();

if (typeof dbs == 'object') {
    partial = true;
    dbs.forEach(function(d) {
        validateDatabase(d);
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
            validateCollection(d, coll);
        }
    });
}

if (!partial) {
    db.getMongo().getDBNames({readPreference: 'primaryPreferred'}).forEach(function(d) {
        validateDatabase(d);
    });
}

var timerEnd = new Date();
var helloDoc = (typeof db.hello !== 'function') ? db.isMaster() : db.hello();
printFunction({
    validation: (allClean ? "passed" : "failed"),
    valid: allClean,
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
