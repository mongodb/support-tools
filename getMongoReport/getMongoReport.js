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

var _version = "2.6.0";

(function () {
   "use strict";
}());

// For MongoDB 2.4 and before
if (DB.prototype.getUsers == null) {
    DB.prototype.getUsers = function (args) {
        var cmdObj = {usersInfo: 1};
        Object.extend(cmdObj, args);
        var res = this.runCommand(cmdObj);
        if (!res.ok) {
            var authSchemaIncompatibleCode = 69;
            if (res.code == authSchemaIncompatibleCode ||
                    (res.code == null && res.errmsg == "no such cmd: usersInfo")) {
                // Working with 2.4 schema user data
                return this.system.users.find({}).toArray();
            }
            throw Error(res.errmsg);
        }
        return res.users;
    }
}

// For MongoDB 2.4 and before
if (DB.prototype.getRoles == null) {
    DB.prototype.getRoles = function (args) {
        return "No custom roles";
    }
}

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

    printInfo("Sharding version",
              function(){return db.getSiblingDB("config").getCollection("version").findOne()},
              section);

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
                            if ( coll.dropped === false ){
                                collDoc = {};
                                collDoc['_id'] = coll._id;
                                collDoc['key'] = coll.key;

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

                                collDoc['chunks'] = [];
                                configDB.chunks.find( { "ns" : coll._id } ).sort( { min : 1 } ).forEach(
                                    function(chunk) {
                                        chunkDoc = {}
                                        chunkDoc['min'] = chunk.min;
                                        chunkDoc['max'] = chunk.max;
                                        chunkDoc['shard'] = chunk.shard;
                                        chunkDoc['jumbo'] = chunk.jumbo ? true : false;
                                        collDoc['chunks'].push(chunkDoc);
                                    }
                                );

                                collDoc['tags'] = [];
                                configDB.tags.find( { ns : coll._id } ).sort( { min : 1 } ).forEach(
                                    function(tag) {
                                        tagDoc = {}
                                        tagDoc['tag'] = tag.tag;
                                        tagDoc['min'] = tag.min;
                                        tagDoc['max'] = tag.max;
                                        collDoc['tags'].push(tagDoc);
                                    }
                                );
                            }
                            doc['collections'].push(collDoc);
                        }
                    );
                }
                ret.push(doc);
            }
        );
        return ret;
    }, section);
}

function printInfo(message, command, section, printCapture) {
    var result = false;
    printCapture = (printCapture === undefined ? false: true);
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
        }
        result = null
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
    _output.push(doc);
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
}

function printReplicaSetInfo() {
    section = "replicaset_info";
    printInfo('Replica set config', function(){return rs.conf()}, section);
    printInfo('Replica status',     function(){return rs.status()}, section);
    printInfo('Replica info',       function(){return db.getReplicationInfo()}, section);
    printInfo('Replica slave info', function(){return db.printSlaveReplicationInfo()}, section, true);
}

function printDataInfo(isMongoS) {
    section = "data_info";
    var dbs = printInfo('List of databases', function(){return db.getMongo().getDBs()}, section);

    if (dbs.databases) {
        dbs.databases.forEach(function(mydb) {
            var collections = printInfo("List of collections for database '"+ mydb.name +"'",
                                        function(){return db.getSiblingDB(mydb.name).getCollectionNames()}, section);

            printInfo('Database stats (MB)',
                      function(){return db.getSiblingDB(mydb.name).stats(1024*1024)}, section);
            if (!isMongoS) {
                printInfo('Database profiler',
                          function(){return db.getSiblingDB(mydb.name).getProfilingStatus()}, section);
            }

            if (collections) {
                collections.forEach(function(col) {
                    printInfo('Collection stats (MB)',
                              function(){return db.getSiblingDB(mydb.name).getCollection(col).stats(1024*1024)}, section);
                    if (isMongoS) {
                        printInfo('Shard distribution',
                                  function(){return db.getSiblingDB(mydb.name).getCollection(col).getShardDistribution()}, section, true);
                    }
                    printInfo('Indexes',
                              function(){return db.getSiblingDB(mydb.name).getCollection(col).getIndexes()}, section);
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
                    if (col != "system.users") {
                        printInfo('Sample document',
                                  function(){
					var lastValCursor = db.getSiblingDB(mydb.name).getCollection(col).find().sort({'$natural': -1}).limit(-1);
					if (lastValCursor.hasNext()) {
						return lastValCursor.next()
					}
					else {
						return null;
					}
				  }, section);
                    }
                });
            }
        });
    }
}

function printShardOrReplicaSetInfo() {
    section = "shard_or_replicaset_info";
    printInfo('isMaster', function(){return db.isMaster()}, section);
    var state;
    var stateInfo = rs.status();
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
            rs.slaveOk();
        }
        printReplicaSetInfo();
    }
    return false;
}

function printAuthInfo() {
    section = "auth_info";
    db = db.getSiblingDB('admin');
    printInfo('Users', function(){return db.getUsers()}, section);
    printInfo('Custom roles', function(){return db.getRoles()}, section);
}


if (typeof _printJSON === "undefined") var _printJSON = false;
if (typeof _ref === "undefined") var _ref = null;
var _output = [];
var _tag = ObjectId();
if (! _printJSON) {
    print("================================");
    print("MongoDB Config and Schema Report");
    print("getMongoData.js version " + _version);
    print("================================");
}
var _host = hostname();
printServerInfo();
var isMongoS = printShardOrReplicaSetInfo();
printAuthInfo();
printDataInfo(isMongoS);
if (_printJSON) print(JSON.stringify(_output, jsonStringifyReplacer, 4));
