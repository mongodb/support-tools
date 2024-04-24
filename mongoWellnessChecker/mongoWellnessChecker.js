/* global db, rs, print, printjson */

/* =================================================
 * mongoWellnessChecker.js: MongoDB Config and Schema Report using mongosh
 * =================================================
 *
 * Copyright MongoDB, Inc, 2023
 *
 * Gather MongoDB configuration and schema information with mongosh shell. 
 *
 * WARNING: DO NOT USE Legacy mongo shell with this script. 
 *
 * To execute on a locally running mongod on default port (27017) without
 * authentication, run:
 *
 *     mongosh getMongoWellnessChecker.js > getMongoWellnessChecker.log
 *
 * To execute on a remote mongod or mongos with authentication, run:
 *
 *     mongosh HOST:PORT/admin -u ADMIN_USER -p ADMIN_PASSWORD getMongoWellnessChecker.js > getMongoWellnessChecker.log
 *
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


//Make the ObjectID format in the output same as the legacy getMongoData script
if (typeof (ObjectId) != "undefined") {

	ObjectId.prototype.toJSON = ObjectId.prototype.toExtendedJSON;
}

//Make the Timestamp format in the output same as the legacy getMongoData script
if (typeof (Timestamp) != "undefined") {


    Timestamp.prototype.toJSON = function() {
        return this.toStringIncomparable(); 
     };

    Timestamp.prototype.toStringIncomparable = function() {
        var t = this.hasOwnProperty("t") ? this.t : this.high;
        var i = this.hasOwnProperty("i") ? this.i : this.low;
	var timestamplegacy = {};
        var tsdoc = {} ;
        tsdoc['t'] = t;
        tsdoc['i'] = i;
	timestamplegacy['$timestamp']=tsdoc;
        return timestamplegacy;

    };
} else {
    print("warning: no Timestamp class");
}

// Taken from legacy getMongoData.js script and then modified it to work with mongosh 
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
        } catch(e) { 
		print(e);
	}
        finally {
            // Stop capturing print() output
            print = __orig_print;
        }
        return res;
    };
}

// For use in JSON.stringify to properly serialize known types
function jsonStringifyReplacer(k, v){
    //if (v instanceof ObjectId)
    //    return { "$oid" : v.toString() };
    if (v instanceof Long)
        return { "$numberLong" : longmangle(v) };
    if (v instanceof Int32)
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


//As of mongosh 1.8.0 Long and NumberLong appear to be used interchangeably
function longmangle(n) {
    if (!(n instanceof NumberLong || n instanceof Long))
        return null;
    var s = n.toString();
    return s;
}

function printInfo(message, command, section="notdefined", printCapture=false, commandParameters={}) {

	//validation checks
	//message is mandatory arg
	try {

		if (typeof message !== 'string') {
			throw new Error("printInfo message argument is not a string");
		} 
		//command is mandatory arg
		if (typeof command !== 'function') {
			throw new Error("printInfo command argument is not a function");
		}
		err=null;
	} catch(err) {
		throw new Error("printInfo error handing message or command: " + err);
	}

	const testFunction = function () { return false; };
	const allowedCommandFunctionNames = [testFunction.name,"printServerInfoShellVersion","printServerInfoShellHostname","printServerInfoCurrentDBname","printServerInfoCurrentDBname","printServerInfoServerStatus","printServerInfoHostInfo","printServerInfoCmdLineInfo","printServerInfoServerBuildInfo","printServerInfoServerParams","printReplicaSetInfoRSConfig","printReplicaSetInfoRSStatus","printReplicaSetInfoGetReplicationInfo","printReplicaSetInfoPrintSecondaryReplicationInfo","printShardOrReplicaSetInfoIsMaster","printUserAuthInfoDBUserCount","printUserAuthInfoCustomRoleCount","printShardInfoGetShardingVersion","printShardInfoGetShardingSettings","printShardInfoGetMongoses","printShardInfoGetShards","printShardInfoGetShardedDatabases","printShardInfoGetBalancerStatus","printDataInfoListDatabases","printDataInfoListCollectionsForDatabases","printDataInfoDBStats","printDataInfoGetProfilingStatusForDB","printDataInfoGetCollStats","printDataInfoListIndexesForColl","printDataInfoIndexStats","printDataInfoShardDistribution"];

	if (!allowedCommandFunctionNames.includes(command.name)) {
		throw new Error("printInfo Not in the approved list of functions: " + command.name);
	}

	var result = false; 

	//printCapture default value of false of type boolean is declared in the function signature
	//if printCapture is defined it must be boolean
	if (typeof printCapture !== 'boolean') {
		throw new Error("printInfo printCapture argument is not a boolean");
	} 

	if (! _printJSON) print("\n** " + message + ":");
	startTime = new Date();
	try {

		if (printCapture) { 

			result = print.captureAllOutput(command);
		} else {

			result = command();
		}
		err = null;
	} catch(err) {
		if (! _printJSON) {
			print("printInfo Error running '" + command + "':");
			print(err);
		} else {
			throw new Error("printInfo Error running '" + command + "': " + err);
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

	try { 


		//section parameter default value set to "notdefined" string which is not used in any other calls to printInfo
		if (section !== "notdefined") { 
			doc['section'] = section; 
			doc['subsection'] = message.toLowerCase().replace(/ /g, "_"); 
		} else { 
			doc['section'] = message.toLowerCase().replace(/ /g, "_"); 
		}
		err = null;
	} catch(err) {
		throw new Error("printInfo Error handling section parameter: " + err);
	}

	doc['ts'] = {'start': startTime, 'end': endTime};
	doc['version'] = _version;

	try { 


		//commandParameters parameter default value set to {} 
		if (commandParameters !== {} ) { doc['commandParameters'] = commandParameters; }
	} catch(err) {
		throw new Error("printInfo Error handling commandParameters");
	}
	_output.push(doc);
	if (! _printJSON) printjson(result);
	return result;
}

// This function has been included as is from the legacy getMongoData.js script 
function printShardInfo(){

	const printShardInfoGetShardingVersion = function(){return configDB.getCollection('version').findOne();}; 
	const printShardInfoGetShardingSettings = function(){return configDB.settings.find().sort({ _id : 1 }).toArray();}; 
	const printShardInfoGetMongoses = function(){return configDB.mongos.find().sort({ _id : 1 }).toArray();}; 
	const printShardInfoGetShards = function(){return configDB.shards.find().sort({ _id : 1 }).toArray();}; 
	//legacy Regex.escape() replacement
	const escapeRegex = function(text){return text.replace(/[-[\]{}()*+?.,\\^$|#\s]/g, "\\$&");};
	const printShardInfoGetShardedDatabases = function(){
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
                        escapeRegex(db._id) + "\\." ) } ).
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
                                            chunkDoc = {}
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
                                        tagDoc = {}
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
    }; 
	const printShardInfoGetBalancerStatus = function(){return db.adminCommand({balancerStatus: 1});}; 
	const printShardInfoGetRecentMigrations = function(){return sh.getRecentMigrations();}; 
	const printShardInfoGetRecentFailedBalancerRounds = function(){return sh.getRecentFailedRounds();}; 

	section = "shard_info"; 
	var configDB = db.getSiblingDB("config"); 
	
	printInfo("Sharding version", printShardInfoGetShardingVersion, section); 
	printInfo("Sharding settings", printShardInfoGetShardingSettings, section); 
	printInfo("Routers", printShardInfoGetMongoses, section); 
	printInfo("Shards", printShardInfoGetShards, section); 
	printInfo("Sharded databases", printShardInfoGetShardedDatabases, section); 
	printInfo('Balancer status', printShardInfoGetBalancerStatus, section); 
	
	if (sh.getRecentMigrations) { 
		// Function does not exist in older shell versions (2.6 and below) 
		printInfo('Recent chunk migrations', printShardInfoGetRecentMigrations, section); 
	} else { 
		if (! _printJSON) print("\n** Recent chunk migrations: n/a") 
	} 
	
	if (sh.getRecentFailedRounds) { 
		// Function does not exist in older shell versions (2.6 and below) 
		printInfo('Recent failed balancer rounds', printShardInfoGetRecentFailedBalancerRounds, section); 
	} else { 
		if (! _printJSON) print("\n** Recent failed balancer rounds: n/a") 
	}
}

function printDataInfo(isMongoS) {


	section = "data_info"; 

	const printDataInfoListDatabases = function(){return db.getMongo().getDBs();}; 


	var dbs = printInfo('List of databases', printDataInfoListDatabases, section); 
	var collections_counter = 0; 

	if (dbs.databases) { 
		dbs.databases.forEach(function(mydb) {




				//the functions that access variables in scope of the parent function need to be defined locally 
				const printDataInfoListCollectionsForDatabases =  function(){ 
				var collectionNames = [] 
				// Filter out views 
				db.getSiblingDB(mydb.name).getCollectionInfos({"type": "collection"}).forEach(function(collectionInfo) { 
						collectionNames.push(collectionInfo['name']); 
						}); 

				// Filter out the collections with the "system." prefix in the system databases 
				if (mydb.name == "config" || mydb.name == "local" || mydb.name == "admin") { 
				return collectionNames.filter(function (str) { return str.indexOf("system.") != 0; })
				.filter(function(str) { return str.indexOf("replset.") != 0; }); 
				} else { return collectionNames; } }; 

				var collections = printInfo("List of collections for database '"+ mydb.name +"'", printDataInfoListCollectionsForDatabases, section); 


				const printDataInfoDBStats = function(){return db.getSiblingDB(mydb.name).stats(1024*1024);}; 
				printInfo('Database stats (MB)', printDataInfoDBStats, section); 


				const printDataInfoGetProfilingStatusForDB = function(){return db.getSiblingDB(mydb.name).getProfilingStatus();}; 
				if (!isMongoS) { printInfo("Database profiler for database '"+ mydb.name + "'", printDataInfoGetProfilingStatusForDB, section, false, {"db": mydb.name}) }

				if (collections) {


					collections.forEach(function(col) { 


							const printDataInfoGetCollStats = function(){return db.getSiblingDB(mydb.name).getCollection(col).stats(1024*1024);}; 
							printInfo('Collection stats (MB)',printDataInfoGetCollStats, section); 

							collections_counter++; 

							if (collections_counter > _maxCollections) { 
							var err_msg = 'Already asked for stats on '+collections_counter+' collections ' + 
							'which is above the max allowed for this script. No more database and ' + 
							'collection-level stats will be gathered, so the overall data is ' + 
							'incomplete. ' 
							if (_printJSON) { 
							err_msg += 'The "subsection" fields have been prefixed with "INCOMPLETE_" ' + 
							'to indicate that partial data has been outputted.' } 
							throw { name: 'MaxCollectionsExceededException', message: err_msg } 
							} 

							const printDataInfoShardDistribution = function(){return db.getSiblingDB(mydb.name).getCollection(col).getShardDistribution();}; 
							if (isMongoS) { printInfo('Shard distribution', printDataInfoShardDistribution, section, true); } 


							const printDataInfoListIndexesForColl = function(){return db.getSiblingDB(mydb.name).getCollection(col).getIndexes();}; 
							printInfo('Indexes', printDataInfoListIndexesForColl, section, false, {"db": mydb.name, "collection": col}); 


							const printDataInfoIndexStats = function(){
								try {
									var res = db.getSiblingDB(mydb.name).runCommand( {
aggregate: col,
pipeline: [
{$indexStats: {}},
{$group: {_id: "$key", stats: {$push: {accesses: "$accesses.ops", host: "$host", since: "$accesses.since"}}}},
{$project: {key: "$_id", stats: 1, _id: 0}}
],
cursor: {}
});
err=null;
}catch(err) {
	return "Error running index stats on Database " + mydb.name + " Collection " + col + " Error: " + err;
}

//It is assumed that there always will be a single batch as collections
//are limited to 64 indexes and usage from all shards is grouped
//into a single document
try {
	if (res.hasOwnProperty('cursor') && res.cursor.hasOwnProperty('firstBatch')) {
		res.cursor.firstBatch.forEach(
				function(d){
				d.stats.forEach(
						function(d){
						d.since = d.since.toUTCString();
						})
				});
	} 
	err=null;
} catch(err) {
	return "Error running index stats on Database " + mydb.name + " Collection " + col + " res processing Error: " + err;
}

return res;
};

printInfo('Index Stats', printDataInfoIndexStats, section);
});
}
});
}
}

function printReplicaSetInfo() {
	const printReplicaSetInfoRSConfig = function(){return rs.conf();};
	const printReplicaSetInfoRSStatus = function(){return rs.status();};
	const printReplicaSetInfoGetReplicationInfo = function(){return db.getReplicationInfo();};
	const printReplicaSetInfoPrintSecondaryReplicationInfo = function(){return db.printSecondaryReplicationInfo();}; 
	
	section = "replicaset_info"; 
	printInfo('Replica set config', printReplicaSetInfoRSConfig, section); 
	printInfo('Replica status', printReplicaSetInfoRSStatus, section); 
	printInfo('Replica info', printReplicaSetInfoGetReplicationInfo, section); 
	printInfo('Replica slave info', printReplicaSetInfoPrintSecondaryReplicationInfo, section, true);
}

function printServerInfo() {
	const printServerInfoShellVersion = function() { return version(); };
	const printServerInfoShellHostname = function() { /**mongosh way*/ return os.hostname();}; 
	const printServerInfoCurrentDBname = function() { return db.getName();};
	const printServerInfoServerStatus = function() { return db.serverStatus();};
	const printServerInfoHostInfo = function(){return db.hostInfo();};
	const printServerInfoCmdLineInfo = function(){return db.serverCmdLineOpts();};
	const printServerInfoServerBuildInfo = function(){return db.serverBuildInfo();};
	const printServerInfoServerParams = function(){return db.adminCommand({getParameter: '*'});}; 

	section = "server_info"; 
	printInfo('Shell version', printServerInfoShellVersion, section); 
	printInfo('Shell hostname', printServerInfoShellHostname, section); 
	printInfo('db', printServerInfoCurrentDBname, section); 
	printInfo('Server status info', printServerInfoServerStatus, section); 
	printInfo('Host info', printServerInfoHostInfo, section); 
	printInfo('Command line info',  printServerInfoCmdLineInfo, section); 
	printInfo('Server build info',  printServerInfoServerBuildInfo, section); 
	printInfo('Server parameters',  printServerInfoServerParams, section);
}


function printShardOrReplicaSetInfo() {

	const printShardOrReplicaSetInfoIsMaster = function(){return db.isMaster();}; 
	section = "shard_or_replicaset_info"; 
	printInfo('isMaster', printShardOrReplicaSetInfoIsMaster, section); 

	var state; 
	var stateInfo; 

	try { 
		stateInfo = rs.status(); 
		stateInfo.members.forEach( function( member ) { if ( member.self ) { state = member.stateStr; } } ); 
		if ( !state ) state = stateInfo.myState; 
	} 
	catch(e) { 
		if(e.info === 'mongos'){state="mongos";} 
		else if(e.codeName === 'NoReplicationEnabled'){state="standalone";}
		else {console.log("Unexpected error don't know what to do: "+ e);}
	}

	if (! _printJSON) print("\n** Connected to " + state); 
	if (state == "mongos") { 
		printShardInfo(); 
		return true; 
	} else if (state != "standalone") { 
		if (state == "SECONDARY" || state == 2) { 
			db.getMongo().setReadPref('secondary');
		} 
		printReplicaSetInfo(); 
	} 
	return false; 
}

function printUserAuthInfo() { 
	section = "user_auth_info"; 
	db = db.getSiblingDB('admin');
	const printUserAuthInfoDBUserCount = function(){return db.system.users.countDocuments();};
	const printUserAuthInfoCustomRoleCount = function(){return db.system.roles.countDocuments();}; 
	
	printInfo('Database user count', printUserAuthInfoDBUserCount, section); 
	printInfo('Custom role count', printUserAuthInfoCustomRoleCount, section);
}


var _version = "1.0.0";


(function () {
   "use strict";
}());

function updateDataInfoAsIncomplete(isMongoS) {
  for (i = 0; i < _output.length; i++) {
    if(_output[i].section != "data_info") { continue; }
    _output[i].subsection = "INCOMPLETE_"+ _output[i].subsection;
  }
}


if (typeof _printJSON === "undefined") var _printJSON = true;
if (typeof _printChunkDetails === "undefined") var _printChunkDetails = false;
if (typeof _ref === "undefined") var _ref = null;

// Limit the number of collections this script gathers stats on in order
// to avoid the possibility of running out of file descriptors. This has
// been set to an extremely conservative number but can be overridden
// by setting _maxCollections to a higher number prior to running this
// script.
if (typeof _maxCollections === "undefined") var _maxCollections = 2500;

var _total_collection_ct = 0;
var _output = [];
var _tag = ObjectId();
if (! _printJSON) {
    print("================================");
    print("MongoDB Config and Schema Report");
    print("getMongoData.js version " + _version);
    print("================================");
}

try {
  var _host = db.hostInfo().system.hostname;
} catch(e) {
  throw new Error(`Unable to set _host global variable ${e}`);
}

try { 

	printServerInfo(); 
	var isMongoS = printShardOrReplicaSetInfo(); 
	printUserAuthInfo(); 
	printDataInfo(isMongoS);
} catch(e) {
    // To ensure that the operator knows there was an error, print the error
    // even when outputting JSON to make it invalid JSON.
    print('\nERROR: '+e.message);

    if (e.name === 'MaxCollectionsExceededException') {
      // Prefix the "subsection" fields with "INCOMPLETE_" to make
      // it clear that the database and collection info are likely to be
      // incomplete.
      updateDataInfoAsIncomplete(isMongoS);
    } else {
      quit(1);
   }
}

// Print JSON output 

if (_printJSON) print(JSON.stringify(_output, jsonStringifyReplacer, 4));
