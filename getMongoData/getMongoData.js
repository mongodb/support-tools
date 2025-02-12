/* global db, tojson, tojsononeline, rs, print, printjson */

/* =================================================
 * getMongoData.js: MongoDB Config and Schema Report
 * =================================================
 *
 * Copyright MongoDB, Inc, 2015
 *
 * Gather MongoDB configuration and schema information.
 *
 * To execute on a locally running mongod on default port (27017) without
 * authentication, run:
 *
 *     mongo getMongoData.js > getMongoData.log
 *
 * To execute on a remote mongod or mongos with authentication, run:
 *
 *     mongo HOST:PORT/admin -u ADMIN_USER -p ADMIN_PASSWORD getMongoData.js > getMongoData.log
 *
 * For details, see
 * https://github.com/mongodb/support-tools/tree/master/getMongoData.
 *
 *
 * DISCLAIMER
 *
 * Please note: all tools/ scripts in this repo are released for use "AS
 * IS" without any warranties of any kind, including, but not limited to
 * their installation, use, or performance. We disclaim any and all
 * warranties, either express or implied, including but not limited to
 * any warranty of noninfringement, merchantability, and/ or fitness for
 * a particular purpose. We do not warrant that the technology will
 * meet your requirements, that the operation thereof will be
 * uninterrupted or error-free, or that any errors will be corrected.
 *
 * Any use of these scripts and tools is at your own risk. There is no
 * guarantee that they have been through thorough testing in a
 * comparable environment and we are not responsible for any damage
 * or data loss incurred with their use.
 *
 * You are responsible for reviewing and testing any scripts you run
 * thoroughly before use in any non-testing environment.
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

var _version = "3.1.0";

(function () {
   "use strict";
}());

// Taken from the >= 3.1.9 shell to capture print output
if (typeof print.captureAllOutput === "undefined") {
    print.captureAllOutput = function (fn, args) {
        var res = {};
        res.output = [];
        var __orig_print = print;
        print = function () {
            Array.prototype.push.apply(res.output, Array.prototype.slice.call(arguments).join(" ").split("\n"));
        };
        try {
            res.result = fn.apply(undefined, args);
        }
        finally {
            // Stop capturing print() output
            print = __orig_print;
        }
        return res;
    };
}

// Convert NumberLongs to strings to save precision
function longmangle(n) {
    if (! n instanceof NumberLong)
        return null;
    var s = n.toString();
    s = s.replace("NumberLong(","").replace(")","");
    if (s[0] == '"')
        s = s.slice(1, s.length-1)
    return s;
}

// For use in JSON.stringify to properly serialize known types
function jsonStringifyReplacer(k, v){
    if (v instanceof ObjectId)
        return { "$oid" : v.valueOf() };
    if (v instanceof NumberLong)
        return { "$numberLong" : longmangle(v) };
    if (v instanceof NumberInt)
        return v.toNumber();
    // For ISODates; the $ check prevents recursion
    if (typeof v === "string" && k.startsWith('$') == false){
        try {
            iso = ISODate(v);
            return { "$date" : iso.valueOf() };
        }
        // Nothing to do here, we'll get the return at the end
        catch(e) {}
    }
    return v;
}

// Copied from Mongo Shell
function printShardInfo(){
    section = "shard_info";
    var configDB = db.getSiblingDB("config");

    printInfo("Sharding version", function(){
        return configDB.getCollection('version').findOne();
    }, section);

    printInfo("Sharding settings", function(){
        return configDB.settings.find().sort({ _id : 1 }).toArray();
    }, section);

    printInfo("Routers", function(){
        return configDB.mongos.find().sort({ _id : 1 }).toArray();
    }, section);

    printInfo("Shards", function(){
        return configDB.shards.find().sort({ _id : 1 }).toArray();
    }, section);

    printInfo("Sharded databases", function(){
        var ret = [];
        configDB.databases.find().sort( { name : 1 } ).forEach(
            function(db) {
                doc = {};
                for (k in db) {
                    if (db.hasOwnProperty(k)) doc[k] = db[k];
                }
                if (db.partitioned) {
                    doc['collections'] = [];
                    configDB.collections.find( { _id : new RegExp( "^" +
                        RegExp.escape(db._id) + "\\." ) } ).
                        sort( { _id : 1 } ).forEach( function( coll ) {
                            if ( coll.dropped !== true ){
                                collDoc = {};
                                collDoc['_id'] = coll._id;
                                collDoc['key'] = coll.key;
                                collDoc['unique'] = coll.unique;

                                var res = configDB.chunks.aggregate(
                                    { "$match": { ns: coll._id } },
                                    { "$group": { _id: "$shard", nChunks: { "$sum": 1 } } }
                                );
                                // MongoDB 2.6 and above returns a cursor instead of a document
                                res = (res.result ? res.result : res.toArray());

                                collDoc['distribution'] = [];
                                res.forEach( function(z) {
                                    chunkDistDoc = {'shard': z._id, 'nChunks': z.nChunks};
                                    collDoc['distribution'].push(chunkDistDoc);
                                } );

                                if (_printChunkDetails) {
                                    collDoc['chunks'] = [];
                                    configDB.chunks.find( { "ns" : coll._id } ).sort( { min : 1 } ).forEach(
                                        function(chunk) {
                                            chunkDoc = {};
                                            chunkDoc['min'] = chunk.min;
                                            chunkDoc['max'] = chunk.max;
                                            chunkDoc['shard'] = chunk.shard;
                                            chunkDoc['jumbo'] = chunk.jumbo ? true : false;
                                            collDoc['chunks'].push(chunkDoc);
                                        }
                                    );
                                }

                                collDoc['tags'] = [];
                                configDB.tags.find( { ns : coll._id } ).sort( { min : 1 } ).forEach(
                                    function(tag) {
                                        tagDoc = {};
                                        tagDoc['tag'] = tag.tag;
                                        tagDoc['min'] = tag.min;
                                        tagDoc['max'] = tag.max;
                                        collDoc['tags'].push(tagDoc);
                                    }
                                );
                                doc['collections'].push(collDoc);
                            }
                        }
                    );
                }
                ret.push(doc);
            }
        );
        return ret;
    }, section);

    printInfo('Balancer status', function(){return db.adminCommand({balancerStatus: 1})}, section);

    if (sh.getRecentMigrations) { // Function does not exist in older shell versions (2.6 and below)
        printInfo('Recent chunk migrations', function(){return sh.getRecentMigrations()}, section);
    } else {
        if (! _printJSON) print("\n** Recent chunk migrations: n/a")
    }

    if (sh.getRecentFailedRounds) { // Function does not exist in older shell versions (2.6 and below)
        printInfo('Recent failed balancer rounds', function(){return sh.getRecentFailedRounds()}, section);
    } else {
        if (! _printJSON) print("\n** Recent failed balancer rounds: n/a")
    }
}

var _JSONPrefix = "";
function printInfo(message, command, section, printCapture, commandParameters) {
    var result = false;
    if (typeof printCapture === "undefined") var printCapture = false;
    if (! _printJSON) print("\n** " + message + ":");
    startTime = new Date();
    try {
        if (printCapture) {
            result = print.captureAllOutput(command);
        } else {
            result = command();
        }
        err = null
    } catch(err) {
        if (! _printJSON) {
            print("Error running '" + command + "':");
            print(err);
        } else {
            throw("Error running '" + command + "': " + err);
        }
    }
    endTime = new Date();
    doc = {};
    doc['command'] = command.toString();
    doc['error'] = err;
    doc['host'] = _host;
    doc['ref'] = _ref;
    doc['tag'] = _tag;
    doc['output'] = result;
    if (typeof(section) !== "undefined") {
        doc['section'] = section;
        doc['subsection'] = message.toLowerCase().replace(/ /g, "_");
    } else {
        doc['section'] = message.toLowerCase().replace(/ /g, "_");
    }
    doc['ts'] = {'start': startTime, 'end': endTime};
    doc['version'] = _version;
    if (typeof commandParameters !== undefined) {
      doc['commandParameters'] = commandParameters
    }

    // Stream JSON array element.
    if (_printJSON) {
        print(_JSONPrefix, JSON.stringify(doc, jsonStringifyReplacer, 4));
        _JSONPrefix = ",";
    }

    if (! _printJSON) printjson(result);
    return result;
}

function printServerInfo() {
    section = "server_info";
    printInfo('Shell version',      version, section);
    printInfo('Shell hostname',     hostname, section);
    printInfo('db',                 function(){return db.getName()}, section);
    printInfo('Server status info', function(){return db.serverStatus()}, section);
    printInfo('Host info',          function(){return db.hostInfo()}, section);
    printInfo('Command line info',  function(){return db.serverCmdLineOpts()}, section);
    printInfo('Server build info',  function(){return db.serverBuildInfo()}, section);
    printInfo('Server parameters',  function(){return db.adminCommand({getParameter: '*'})}, section);
}

function printReplicaSetInfo() {
    section = "replicaset_info";
    printInfo('Replica set config', function(){return rs.conf()}, section);
    printInfo('Replica status',     function(){return rs.status()}, section);
    printInfo('Replica info',       function(){return db.getReplicationInfo()}, section);
    printInfo('Replica slave info', function(){return db.printSlaveReplicationInfo()}, section, true);
}

function printUserAuthInfo() {
  section = "user_auth_info";
  db = db.getSiblingDB('admin');
  if (typeof db.system.users.countDocuments === 'function') {
    printInfo('Database user count', function(){return db.system.users.countDocuments({})}, section);
    printInfo('Custom role count', function(){return db.system.roles.countDocuments({})}, section);
  } else {
    printInfo('Database user count', function(){return db.system.users.count()}, section);
    printInfo('Custom role count', function(){return db.system.roles.count()}, section);
  }
}

// find all QE collections
// Outputs the following JSON:
/*
[
    {
        namespace: "qe_db.qe_coll",
        escCollectionInfo: {
            namespace: "qe_db.enxcol_.qe_coll.esc",
            exists: true/false,
            isClusteredCollection: true/false,
            documentCount: 1078,
            anchorCount: 78,
            nonAnchorCount: 1000,
        },
        ecocCollectionInfo: {
            namespace: "qe_db.enxcol_.qe_coll.ecoc",
            exists: true/false,
            documentCount: 10780,
            isClusteredCollection: true/false,
            compactTempCollectionExists: true/false,
        },
        safeContentInfo: {
            safeContentIndexed: true/false,
            indexedEncryptedDocumentsWithMissingSafeContentTags: 778,
        },
        shardingInfo: {
            isSharded: true/false,
            shardingStatus: {}
        },
        fields: {...},
    },
    {
        ...
    },
    ...
]
*/
function collectQueryableEncryptionInfo(isMongoS) {
    const output = [];
    const dbs = db.getMongo().getDBs();
    if (!dbs.databases) {
        return output;
    }
    const getAuxiliaryCollectionInfo = function(db, collName) {
        let collInfos = db.getCollectionInfos({name: collName});
        let exists = (collInfos.length > 0);
        let isClusteredCollection = exists && collInfos[0].hasOwnProperty("options") &&
            collInfos[0].options.hasOwnProperty("clusteredIndex");
        return {exists, isClusteredCollection};
    };

    dbs.databases.forEach(function(someDbInfo) {
        const someDb = db.getSiblingDB(someDbInfo.name);
        const qeCollInfos = someDb.getCollectionInfos(
            {"type": "collection", "options.encryptedFields": {$exists: true}});

        qeCollInfos.forEach(function(someCollInfo) {
            const edcColl = someDb.getCollection(someCollInfo.name);
            const qeEntry = {};

            qeEntry["namespace"] = edcColl.getFullName();
            qeEntry["escCollectionInfo"] = (() => {
                const escColl =
                    someDb.getCollection(someCollInfo.options.encryptedFields.escCollection);
                const {exists, isClusteredCollection} =
                    getAuxiliaryCollectionInfo(someDb, escColl.getName());
                if (!exists) {
                    return {namespace: escColl.getFullName(), exists};
                }
                const documentCount = escColl.countDocuments({});
                const anchorCount = escColl.countDocuments({"value": {"$exists": true}});
                const nonAnchorCount = escColl.countDocuments({"value": {"$exists": false}});
                return {
                    namespace: escColl.getFullName(),
                    exists,
                    isClusteredCollection,
                    documentCount,
                    anchorCount,
                    nonAnchorCount,
                };
            })();
            qeEntry["ecocCollectionInfo"] = (() => {
                const ecocColl =
                    someDb.getCollection(someCollInfo.options.encryptedFields.ecocCollection);
                const {exists, isClusteredCollection} =
                    getAuxiliaryCollectionInfo(someDb, ecocColl.getName());
                if (!exists) {
                    return {namespace: ecocColl.getFullName(), exists};
                }
                const documentCount = ecocColl.countDocuments({});
                const compactTempCollectionExists =
                    someDb.getCollectionInfos({name: ecocColl.getName() + ".compact"}).length > 0;
                return {
                    namespace: ecocColl.getFullName(),
                    exists,
                    isClusteredCollection,
                    documentCount,
                    compactTempCollectionExists
                };
            })();
            qeEntry["safeContentInfo"] = (() => {
                const safeContentIndexed = (edcColl.getIndexes().find(
                    doc => doc.key.hasOwnProperty("__safeContent__")) !== undefined);
                const encryptedFieldPaths = someCollInfo.options.encryptedFields.fields.filter(
                    field => field.hasOwnProperty("queries")).map(field => field.path);
                const missingTags = edcColl.aggregate([
                    {$match: {$and: [
                        {$or: encryptedFieldPaths.map((field) => {return {[field]: {$exists: true}};})},
                        {$or: [{__safeContent__: {$exists: false}}, {__safeContent__: {$size: 0}} ]}
                    ]}},
                    {$count: "count"}
                ]).toArray();
                const indexedEncryptedDocumentsWithMissingSafeContentTags =
                    (missingTags.length > 0) ? missingTags[0].count : 0;
                return {
                    safeContentIndexed,
                    indexedEncryptedDocumentsWithMissingSafeContentTags
                };
            })();
            if (isMongoS) {
                qeEntry["shardingInfo"] = (() => {
                    const configDB = someDb.getSiblingDB("config");
                    let shardDoc = configDB.collections.findOne({_id: edcColl.getFullName()});
                    if (!shardDoc) {
                        return {isSharded: false};
                    }
                    return {
                        isSharded: true,
                        shardKey: shardDoc.key,
                        unique: shardDoc.unique,
                        balancing: !shardDoc.noBalance,
                    };
                })();
            }
            qeEntry["fields"] = someCollInfo.options.encryptedFields.fields;
            output.push(qeEntry);
        });
    });
    return output;
}

function printDataInfo(isMongoS) {
    section = "data_info";
    var dbs = printInfo('List of databases', function(){return db.getMongo().getDBs()}, section);
    var collections_counter = 0;

    if (dbs.databases) {
        dbs.databases.forEach(function(mydb) {
            var collections = printInfo("List of collections for database '"+ mydb.name +"'",
                function() {
                    var collectionNames = []

                    // Filter out views
                    db.getSiblingDB(mydb.name).getCollectionInfos({"type": "collection"}).forEach(function(collectionInfo) {
                        collectionNames.push(collectionInfo['name']);
                    })

                    // Filter out the collections with the "system." prefix in the system databases
                    if (mydb.name == "config" || mydb.name == "local" || mydb.name == "admin") {
                        return collectionNames.filter(function (str) { return str.indexOf("system.") != 0; });
                    } else {
                        return collectionNames;
                    }
                }, section);

            printInfo('Database stats (MB)',
                      function(){return db.getSiblingDB(mydb.name).stats(1024*1024)}, section);
            if (!isMongoS) {
                printInfo("Database profiler for database '"+ mydb.name + "'",
                          function(){return db.getSiblingDB(mydb.name).getProfilingStatus()}, section, false, {"db": mydb.name})
            }

            if (collections) {
                collections.forEach(function(col) {
                    printInfo('Collection stats (MB)',
                              function(){return db.getSiblingDB(mydb.name).getCollection(col).stats(1024*1024)}, section);
                    collections_counter++;
                    if (collections_counter > _maxCollections) {
                        var err_msg = 'Already asked for stats on '+collections_counter+' collections ' +
                          'which is above the max allowed for this script. No more database and ' +
                          'collection-level stats will be gathered, so the overall data is ' +
                          'incomplete. '

                        throw {
                          name: 'MaxCollectionsExceededException',
                          message: err_msg
                        }
                    }
                    if (mydb.name == "config" || mydb.name == "local" || mydb.name == "admin") {
                        // The following command doesn't make any sense to config, local and admin
                        return
                    }
                    if (isMongoS) {
                        printInfo('Shard distribution', function() {
                            try {
                                var result = db.getSiblingDB(mydb.name).getCollection(col).getShardDistribution();
                            } catch(e) {
                                var result = '';
                            }
                            return result;
                        }, section, true);
                    }
                    printInfo('Indexes',
                              function(){return db.getSiblingDB(mydb.name).getCollection(col).getIndexes()}, section, false, {"db": mydb.name, "collection": col});
                    printInfo('Index Stats',
                              function(){
                                var res = db.getSiblingDB(mydb.name).runCommand( {
                                  aggregate: col,
                                  pipeline: [
                                    {$indexStats: {}},
                                    {$group: {_id: "$key", stats: {$push: {accesses: "$accesses.ops", host: "$host", since: "$accesses.since"}}}},
                                    {$project: {key: "$_id", stats: 1, _id: 0}}
                                  ],
                                  cursor: {}
                                });

                                //It is assumed that there always will be a single batch as collections
                                //are limited to 64 indexes and usage from all shards is grouped
                                //into a single document
                                if (res.hasOwnProperty('cursor') && res.cursor.hasOwnProperty('firstBatch')) {
                                  res.cursor.firstBatch.forEach(
                                    function(d){
                                      d.stats.forEach(
                                        function(d){
                                          d.since = d.since.toUTCString();
                                        })
                                    });
                                }

                                return res;
                              }, section);
                });
            }
        });
    }

    printInfo("Queryable Encryption Info", function(){
        return collectQueryableEncryptionInfo(isMongoS);}, section, false);
}

function printShardOrReplicaSetInfo() {
    section = "shard_or_replicaset_info";
    printInfo('isMaster', function(){return db.isMaster()}, section);
    var state;

    // Compatible with mongosh
    try {
        var stateInfo = rs.status();
    } catch (e) {
        var stateInfo = e.errorResponse;
    }
    if (stateInfo.ok) {
        stateInfo.members.forEach( function( member ) { if ( member.self ) { state = member.stateStr; } } );
        if ( !state ) state = stateInfo.myState;
    } else {
        var info = stateInfo.info;
        if ( info && info.length < 20 ) {
            state = info; // "mongos", "configsvr"
        }
        if ( ! state ) state = "standalone";
    }
    if (! _printJSON) print("\n** Connected to " + state);
    if (state == "mongos") {
        printShardInfo();
        return true;
    } else if (state != "standalone" && state != "configsvr") {
        if (state == "SECONDARY" || state == 2) {
            if (rs.secondaryOk) {
                rs.secondaryOk();
            } else {
                rs.slaveOk();
            }
        }
        printReplicaSetInfo();
    }
    return false;
}

// Define _suppressError=true to prevent printing and error message, in case we still want the 
// output to be parsable JSON even in the event of an error. The JSON will contain the error in the 
// last entry of the output array.
if (typeof _suppressError === "undefined") var _suppressError = false;
if (typeof _printJSON === "undefined") var _printJSON = true;
if (typeof _printChunkDetails === "undefined") var _printChunkDetails = false;
if (typeof _ref === "undefined") var _ref = null;

// Limit the number of collections this script gathers stats on in order
// to avoid the possibility of running out of file descriptors. This has
// been set to an extremely conservative number but can be overridden
// by setting _maxCollections to a higher number prior to running this
// script.
if (typeof _maxCollections === "undefined") var _maxCollections = 2500;

// Compatibility issues between mongo and mongosh
if (typeof hostname === 'undefined') hostname = function() {return os.hostname();}
if (typeof RegExp.escape === 'undefined') {
    RegExp.escape = function (string) {
        return string.replace(/[/\-\\^$*+?.()|[\]{}]/g, '\\$&');
    }
}
if (typeof db.printSecondaryReplicationInfo === 'function') {
    db.printSlaveReplicationInfo = db.printSecondaryReplicationInfo;
}

var _total_collection_ct = 0;
var _tag = ObjectId();
if (! _printJSON) {
    print("================================");
    print("MongoDB Config and Schema Report");
    print("getMongoData.js version " + _version);
    print("================================");
} else {
    // Start the JSON array.
    print("[\n");
}

var _host = hostname();
var _error = null;
try {
    printServerInfo();
    var isMongoS = printShardOrReplicaSetInfo();
    printUserAuthInfo();
    printDataInfo(isMongoS);
} catch(e) {
    _error = e.message;
    if (e.name === 'MaxCollectionsExceededException') {
        printInfo("incomplete_databases_and_collections_info", function(){ return e.message; });
    } else {
        printInfo("generic_error", function(){ return e.message; });
    }
}

if (_printJSON) {
    print("]");
}

if(_error) {
    if (!_suppressError) {
        // To ensure that the operator knows there was an error, print the error
        // even when outputting JSON to make it invalid JSON.
        print('\nERROR: '+ _error);
    }
    quit(1);
}