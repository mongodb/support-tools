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

// Copied from Mongo Shell
function printShardInfo(){
    section = "shard_info";
    var configDB = db.getSiblingDB("config");

    printInfo("Sharding version",
              'db.getSiblingDB("config").getCollection("version").findOne()',
              section);

    cmd = function() {
        var ret = [];
        configDB.shards.find().sort({ _id : 1 }).forEach(
            function(z) { ret.push(z); }
        );
        return ret;
    };
    printInfo("Shards", cmd);

    cmd = function() {
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
    }
    printInfo("Sharded databases", cmd);
}

function printInfo(message, command, section, printResult) {
    var result = false;
    printResult = (printResult === undefined ? true : false);
    if (_printOutput) print("\n** " + message + ":");
    startTime = new Date();
    try {
        if (typeof(command) == "string") {
            /* jshint evil:true */
            result = eval(command);
            /* jshint evil:false */
        } else {
            result = command();
        }
        err = null
    } catch(err) {
        if (_printOutput) {
            print("Error running '" + command + "':");
            print(err);
        }
        result = null
    }
    endTime = new Date();
    doc = {};
    doc['command'] = typeof command === "function" ? "it's complicated" : command;
    doc['error'] = err;
    doc['host'] == _host;
    doc['ref'] == ""; // TODO cli speficied?
    doc['rid'] = _runId;
    doc['run'] = _runId.getTimestamp();
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
    if (_printOutput && printResult) printjson(result);
    return result;
}

function printServerInfo() {
    section = "server_info";
    printInfo('Shell version',      'version()', section);
    printInfo('Shell hostname',     'hostname()', section);
    printInfo('db',                 'db.getName()', section);
    printInfo('Server status info', 'db.serverStatus()', section);
    printInfo('Host info',          'db.hostInfo()', section);
    printInfo('Command line info',  'db.serverCmdLineOpts()', section);
    printInfo('Server build info',  'db.serverBuildInfo()', section);
}

function printReplicaSetInfo() {
    section = "replicaset_info";
    printInfo('Replica set config', 'rs.conf()', section);
    printInfo('Replica status',     'rs.status()', section);
    printInfo('Replica info',       'db.getReplicationInfo()', section);
    printInfo('Replica slave info', 'db.printSlaveReplicationInfo()', section, false);
}

function printDataInfo(isMongoS) {
    section = "data_info";
    var dbs = printInfo('List of databases', 'db.getMongo().getDBs()', section);

    if (dbs.databases) {
        dbs.databases.forEach(function(mydb) {
            var inDB = "db.getSiblingDB('"+ mydb.name + "')";
            var collections = printInfo("List of collections for database '"+ mydb.name +"'",
                                        inDB + ".getCollectionNames()", section);

            printInfo('Database stats (MB)',    inDB + '.stats(1024*1024)', section);
            if (!isMongoS) {
                printInfo('Database profiler', inDB + '.getProfilingStatus()', section);
            }

            if (collections) {
                collections.forEach(function(col) {
                    var inCol = inDB + ".getCollection('"+ col + "')";
                    printInfo('Collection stats (MB)',   inCol + '.stats(1024*1024)', section);
                    /*
                    if (isMongoS) {
                        printInfo('Shard distribution', inCol + '.getShardDistribution()', section, false);
                    }
                    */
                    printInfo('Indexes',            inCol + '.getIndexes()', section);
                    if (col != "system.users") {
                        printInfo('Sample document',    inCol + '.findOne()', section);
                    }
                });
            }
        });
    }
}

function printShardOrReplicaSetInfo() {
    section = "shard_or_replicaset_info";
    printInfo('isMaster', 'db.isMaster()', section);
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
    if (_printOutput) print("\n** Connected to " + state);
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
    printInfo('Users', 'db.getUsers()', section);
    printInfo('Custom roles', 'db.getRoles()', section);
}


var _printOutput = true;
var _output = [];
var _runId = ObjectId();
if (_printOutput) {
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
if (! _printOutput) printjson(_output);
