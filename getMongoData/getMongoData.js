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

var _version = "2.5.1";

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
    var configDB = db.getSiblingDB("config");

    printInfo("Sharding version",
              'db.getSiblingDB("config").getCollection("version").findOne()');

    print("\n** Shards:");
    configDB.shards.find().sort({ _id : 1 }).forEach(
        function(z) { print(tojsononeline(z)); }
    );

    print("\n** Sharded databases:");
    configDB.databases.find().sort( { name : 1 } ).forEach(
        function(db) {
            print(tojsononeline(db, "", true));
            if (db.partitioned) {
                configDB.collections.find( { _id : new RegExp( "^" +
                    RegExp.escape(db._id) + "\\." ) } ).
                    sort( { _id : 1 } ).forEach( function( coll ) {
                        if ( coll.dropped === false ){
                            print("    " + coll._id);
                            print("      shard key: " + tojson(coll.key, 0, true));
                            print("      chunks:");

                            var res = configDB.chunks.aggregate(
                                { "$match": { ns: coll._id } },
                                { "$group": { _id: "$shard", nChunks: { "$sum": 1 } } }
                            );
                            // MongoDB 2.6 and above returns a cursor instead of a document
                            res = (res.result ? res.result : res.toArray());

                            var totalChunks = 0;
                            res.forEach( function(z) {
                                totalChunks += z.nChunks;
                                print("        " + z._id + ": " + z.nChunks);
                            } );

                            configDB.chunks.find( { "ns" : coll._id } ).sort( { min : 1 } ).forEach(
                                function(chunk) {
                                    print("        " +
                                        tojson( chunk.min, 0, true) + " -> " +
                                        tojson( chunk.max, 0, true ) +
                                        " on: " + chunk.shard + " " +
                                        ( chunk.jumbo ? "jumbo " : "" )
                                    );
                                }
                            );

                            configDB.tags.find( { ns : coll._id } ).sort( { min : 1 } ).forEach(
                                function(tag) {
                                    print("        tag: " + tag.tag + "  " + tojson( tag.min ) + " -> " + tojson( tag.max ));
                                }
                            );
                        }
                    }
                );
            }
        }
    );
}

function printInfo(message, command, printResult) {
    var result = false;
    printResult = (printResult === undefined ? true : false);
    print("\n** " + message + ":");
    try {
        /* jshint evil:true */
        result = eval(command);
        /* jshint evil:false */
    } catch(err) {
        print("Error running '" + command + "':");
        print(err);
    }
    if (printResult) printjson(result);
    return result;
}

function printServerInfo() {
    printInfo('Shell version',      'version()');
    printInfo('Shell hostname',     'hostname()');
    printInfo('db',                 'db');
    printInfo('Server status info', 'db.serverStatus()');
    printInfo('Host info',          'db.hostInfo()');
    printInfo('Command line info',  'db.serverCmdLineOpts()');
    printInfo('Server build info',  'db.serverBuildInfo()');
}

function printReplicaSetInfo() {
    printInfo('Replica set config', 'rs.conf()');
    printInfo('Replica status',     'rs.status()');
    printInfo('Replica info',       'db.getReplicationInfo()');
    printInfo('Replica slave info', 'db.printSlaveReplicationInfo()', false);

}

function printDataInfo(isMongoS) {
    var dbs = printInfo('List of databases', 'db.getMongo().getDBs()');

    if (dbs.databases) {
        dbs.databases.forEach(function(mydb) {
            var inDB = "db.getSiblingDB('"+ mydb.name + "')";
            var collections = printInfo("List of collections for database '"+ mydb.name +"'",
                                        inDB + ".getCollectionNames()");

            printInfo('Database stats (MB)',    inDB + '.stats(1024*1024)');
            if (!isMongoS) {
                printInfo('Database profiler', inDB + '.getProfilingStatus()');
            }

            if (collections) {
                collections.forEach(function(col) {
                    var inCol = inDB + ".getCollection('"+ col + "')";
                    printInfo('Collection stats (MB)',   inCol + '.stats(1024*1024)');
                    if (isMongoS) {
                        printInfo('Shard distribution', inCol + '.getShardDistribution()', false);
                    }
                    printInfo('Indexes',            inCol + '.getIndexes()');
                    if (col != "system.users") {
                        printInfo('Sample document',    inCol + '.findOne()');
                    }
                });
            }
        });
    }
}

function printShardOrReplicaSetInfo() {
    printInfo('isMaster', 'db.isMaster()');
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
    print("\n** Connected to " + state);
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
    db = db.getSiblingDB('admin');
    printInfo('Users', 'db.getUsers()');
    printInfo('Custom roles', 'db.getRoles()');
}


print("================================");
print("MongoDB Config and Schema Report");
print("getMongoData.js version " + _version);
print("================================");
printServerInfo();
var isMongoS = printShardOrReplicaSetInfo();
printAuthInfo();
printDataInfo(isMongoS);
