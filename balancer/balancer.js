/*
 *
 * balancer.js -- Utility to find chunks, split large chunks, move chunks
 * MongoDB, Inc. 2014 -- Jacob Ribnik
 *
 * TODO Validate user input against config db
 *
 */

var SortSizeLarge = function(a, b){
    return b.size-a.size;
}

var SortSizeSmall = function(a, b){
    return a.size-b.size;
}

var _days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
var _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
var print_ts = function(msg){
    var now = new Date();
    var D = _days[now.getDay()];
    var M = _months[now.getMonth()];
    var d = now.getDate();
    var h = now.getHours();
    if (h < 10){
        h = "0"+h;
    }
    var m = now.getMinutes();
    if (m < 10){
        m = "0"+m;
    }
    var s = now.getSeconds();
    if (s < 10){
        s = "0"+s;
    }
    var ms= now.getMilliseconds();
    if (ms < 10){
        ms = "00"+ms;
    } else if (ms < 100){
        ms = "0"+ms;
    }
    var dateString = D+" "+M+" "+d+" "+h+":"+m+":"+s+"."+ms;
    print(dateString+" "+msg);
}

var ConnectionManager = (function(theDB){
    return {
        globalAuthDoc: null,
        shardAuthDocs: {},
        global: {
            auth: (function(self){return function(user,pwd){
                self.ConnectionManager.globalAuthDoc = {'user':user,'pwd':pwd};
            }})(this)
        },
        shard: {
            auth: (function(self){return function(shard,user,pwd){
                self.ConnectionManager.shardAuthDocs[shard] = {'user':user,'pwd':pwd};
            }})(this)
        },
        localDB: theDB,
        getLocalDB: function() {
            return this.localDB;
        },
        connections: {},

        copyDoc: function(doc){
            var newDoc = {};
            for (var prop in doc) {
                newDoc[prop] = doc[prop];
            }
            return newDoc;
        },
        shardConnect: function(shard){
            if (this.shardAuthDocs[shard._id] || this.globalAuthDoc){
                var auth = true;
            } else {
                var auth = false;
            }

            // TODO decide based on hashed authDoc, not boolean
            // if auth state for connection has changed be sure to reconnect
            // and if there is no existing connection, make one
            if ((! this.connections[shard._id]) || (this.connections[shard._id].auth != auth)){
                conn = new Mongo(shard.host);
                var admin = conn.getDB("admin");

                // try shard specific auth first
                if (this.shardAuthDocs[shard._id]){
                    // copy authDoc as we do not want auth
                    // to modify the original SERVER-11626
                    var authDoc = this.copyDoc(this.shardAuthDocs[shard._id]);

                    if (admin.auth(authDoc) != 1){
                        // try global auth
                        if (this.globalAuthDoc){
                            authDoc = this.copyDoc(this.globalAuthDoc);
                            if (admin.auth(authDoc) != 1){
                                return null;
                            }
                        }
                    }
                } else if (this.globalAuthDoc){
                    var authDoc = this.copyDoc(this.globalAuthDoc);
                    if (admin.auth(authDoc) != 1){
                        return null;
                    }
                }

                this.connections[shard._id] = {'conn':conn,'auth':auth};
                return conn;
            }

            return this.connections[shard._id].conn;
        }
    }
})(db);

var Balancer = {
    connectionManager: ConnectionManager,
    shardConnect: function(shard){
        return this.connectionManager.shardConnect(shard);
    },
    getLocalDB: function(){
        return this.connectionManager.getLocalDB();
    },
    global: {
        auth: (function(self){return function(user,pwd){
            self.ConnectionManager.globalAuthDoc = {'user':user,'pwd':pwd};
        }})(this)
    },
    shard: {
        auth: (function(self){return function(shard,user,pwd){
            self.ConnectionManager.shardAuthDocs[shard] = {'user':user,'pwd':pwd};
        }})(this)
    },

    chunks: null,
    shards: null,

    thinnestShard: function(){
        var shard = "";
        var size = Number.MAX_VALUE;
        for(i in this.shards){
            if (this.shards[i].size < size){
                shard = i;
                size = this.shards[i].size;
            }
        }
        return shard;
    },
    thickestShard: function(){
        var shard = "";
        var size = Number.MIN_VALUE;
        for(i in this.shards){
            if (this.shards[i].size > size){
                shard = i;
                size = this.shards[i].size;
            }
        }
        return shard;
    },

    update: function(){
        return this.init(0, 1);
    },

    init: function(verbose, updateShardsOnly){
        if (typeof verbose === "undefined"){
            verbose = false;
        }
        if (typeof updateShardsOnly === "undefined"){
            updateShardsOnly = false;
        }

        // reset
        if (! updateShardsOnly){
            this.chunks = [];
        }
        this.shards = {};

        var self = this;

        var findObj = {};
        // chunks in ns
        if (this.namespace){
            findObj['ns'] = this.namespace;
        }
        // chunks in shard
        // asking for this._shard is a sanity check here; its existence should
        // already have been validated in run when setShardRestrict was found
        if (this._shardRestrict && this._shard){
            findObj['shard'] = this._shard;
        }
        // only consider the specified chunk range; this is a chunkRestrict
        // on chunk min ;)
        if (this._chunkRange){
            // $minKey -> value
            if (this._chunkRange.first === null && this._chunkRange.last) {
                findObj['min'] = {"$lte": this._chunkRange.last};
            } else
            // value -> $maxKey
            if (this._chunkRange.first && this._chunkRange.last === null) {
                findObj['min'] = {"$gte": this._chunkRange.first};
            } else
            // value -> value
            if (this._chunkRange.first && this._chunkRange.last) {
                findObj['min'] = {"$gte": this._chunkRange.first, "$lte": this._chunkRange.last};
            }
        }
        var chunks = db.getSiblingDB("config").chunks.find(findObj).sort({min:1});

        totalChunks = 0;
        totalSize = 0;
        totalEmpty = 0;
        totalLarge = 0;
        chunks.forEach(function(chunk){
            // get the database we will be running the command against later
            var db1 = db.getSiblingDB(chunk.ns.split(".")[0]);
            // will need this for the dataSize call
            var key = db.getSiblingDB("config").collections.findOne({_id:chunk.ns}).key;
            var dataSizeResult = db1.runCommand({datasize:chunk.ns, keyPattern:key, min:chunk.min, max:chunk.max, estimate:true});

            var ok = dataSizeResult.ok;
            assert.eq(ok, 1);

            var millis = dataSizeResult.millis;
            var size = dataSizeResult.size;
            var numObjects = dataSizeResult.numObjects;

            totalSize += dataSizeResult.size;
            totalChunks++;

            if (size == 0){
                totalEmpty++
            }

            var shard = chunk.shard;

            if (shard in self.shards){
                self.shards[shard].size += size;
                self.shards[shard].nchunk += 1;
            } else {
                self.shards[shard] = {'size':size,'nchunk':1,'nlargeChunk':0};
            }

            var sizeInMB = size/1024./1024.;
            if (sizeInMB > self.maxChunkSize){
                totalLarge++;
                self.shards[shard].nlargeChunk += 1;
            }
            if (! updateShardsOnly){
                if (! self._shard || (self._shard == shard)){
                    // finally, do not split/move empty chunks
                    if (size){
                        self.chunks.push({'id':chunk._id,'ns':chunk.ns,'min':chunk.min,'max':chunk.max,'shard':shard,'size':size});
                    }
                }
            }
        })

        // if destination shard is specified and does not contain
        // chunks, we haven't seen it yet so initialize it
        if (self._destShard && (! (self._destShard in self.shards))){
            self.shards[self._destShard] = {'size':0,'nchunk':0,'nlargeChunk':0};
        } else {
            if (self._destShards){
                for(var dsi = 0; dsi < self._destShards.length; dsi++){
                    var ds = self._destShards[dsi];
                    if (! (ds in self.shards)){
                        self.shards[ds] = {'size':0,'nchunk':0,'nlargeChunk':0};
                    }
                }
            }
        }

        if (! updateShardsOnly){
            if (this.sortBySmallest){
                this.chunks.sort(SortSizeSmall);
            } else {
                this.chunks.sort(SortSizeLarge);
            }
        }

        if (verbose){
            print("*********** Summary Chunk Information ***********");
            if (! this._shardRestrict){
                print("Thinnest Shard: "+this.thinnestShard());
                print("Thickest Shard: "+this.thickestShard());
            }
            if (this._shard){
                var scString = " on "+this._shard+": ";
            } else {
                var scString = ": ";
            }

            print("Total # Chunks"+scString+totalChunks);
            print("Empty # Chunks"+scString+totalEmpty);
            print("Large # Chunks (>"+this.maxChunkSize+"MB)"+scString+totalLarge);
            print("Average Non-Empty Chunk Size (bytes)"+scString+(totalSize/(totalChunks-totalEmpty)).toFixed(0));
            if (this.chunks.length){
                print("Largest Chunk Size (bytes)"+scString+this.chunks[0].size.toFixed(0));
            }
            if (this.verbose && (! this._shardRestrict)){
                print("");
                print("Shard Distribution");
                print("------------------");
                for (var s in this.shards){
                    var shard = this.shards[s];
                    print(s+": "+shard.nchunk+" chunks, "+shard.nlargeChunk+" large chunks (>"+this.maxChunkSize+"MB), "+shard.size+" bytes");
                }
            }
            print("*************************************************");
        }

        return 1;
    },

    // Get splitKeys from mongod hosting given chunk range
    // for given chunk size
    getSplitKeys: function(chunk){
        var shard = this.getLocalDB().getSiblingDB("config").shards.findOne({"_id":chunk.shard});
        if (! shard){
            print_ts("Error finding shard");
            return null
        }
        var host = shard['host'];

        // get shard key
        var key = this.getLocalDB().getSiblingDB("config").collections.findOne({"_id":chunk.ns});
        if (! key){
            print_ts("Error finding key");
            return null
        }
        key = key['key'];

        // connect to host
        var conn = this.shardConnect(shard);
        var db1 = conn.getDB(chunk.ns.split(".")[0]);

        var sv = db1.runCommand({'splitVector':chunk.ns,'keyPattern':key,'min':chunk.min,'max':chunk.max,maxChunkSize:this.maxChunkSize});
        if (! sv.ok){
            print_ts("Error getting splitVector: "+sv.errmsg);
            return null;
        }
        return sv['splitKeys'];
    },

    namespace: null,
    setNamespace: function(ns){
        this.namespace = ns;
    },

    _shard: null,
    setShard: function(shard){
        this._shard = shard;
    },

    _shardRestrict: false,
    setShardRestrict: function(b){
        this._shardRestrict = b;
    },

    _chunkRange: null,
    setChunkRange: function(first, last){
        // null first := $minKey
        // null last := $maxKey
        this._chunkRange = {first:first, last:last};
    },

    _destShard: null,
    setDestShard: function(shard){
        this._destShard = shard;
    },
    _destShards: null,
    setDestShards: function(shardArray){
        // validate array
        if (shardArray instanceof Array){
            this._destShards = shardArray;
        }
    },

    // in MB
    maxChunkSize: 64,
    setMaxChunkSize: function(x) {
        this.maxChunkSize = x;
    },

    maxChunks: -1,
    setMaxChunks: function(n) {
        this.maxChunks = n;
    },

    sortBySmallest: false,
    setSortBySmallest: function(b){
        this.sortBySmallest = b;
    },

    split: true,
    setSplit: function(b){
        this.split= b;
    },
    
    move: false,
    setMove: function(b){
        this.move = b;
    },

    sleep: 5000,
    setSleepMS: function(msecs){
        this.sleep = msecs;
    },

    verbose: false,
    setVerbose: function(b){
        this.verbose = b;
    },

    test: true,
    ready: function(){
        this.test = false;
    },

    disableBalancer: function(){
        sh.setBalancerState(false);
        if (sh.getBalancerState()){
            print_ts("Error disabling balancer");
            return 0;
        } else {
            var k = 0;
            while (sh.isBalancerRunning()){
                k++;
                if (!(k%10)){
                    print_ts("Waiting for balancer to stop running...");
                }
                sleep(1000);
            }
        }

        return 1;
    },

    splitChunk: function(ns, proj){
        var nattempts = 0;
        while (nattempts < 3){
            var res = sh.splitAt(ns, proj);
            if (res['ok'] == 1){
                print_ts("Chunk split successful");
                break;
            } else {
                nattempts++;
            }
        }
        if (nattempts == 3){
            if (this.verbose){
                print_ts("Error splitting chunk at");
                printjson(proj);
                print_ts("Skipping chunk");
            } else {
                print_ts("Error splitting chunk, skipping chunk");
            }
            return 0;
        }

        return 1;
    },

    moveChunk: function(ns, proj, dest){
        var nattempts = 0;
        while (nattempts < 3) {
            var res = sh.moveChunk(ns, proj, dest);
            if (res['ok'] == 1) {
                print_ts("Chunk move successful");
                break;
            } else {
                nattempts++;
            }
        }
        if (nattempts == 3){
            if (this.verbose){
                print_ts("Error moving chunk at");
                printjson(proj);
                print_ts("Skipping chunk");
            } else {
                print_ts("Error moving chunk, skipping chunk");
            }
            return 0;
        }

        return 1;
    },

    run: function(){
        var test = this.test;
        // reset for subsequent runs
        this.test = true;

        // validate configuration
        if (this._shardRestrict && (! this._shard)){
            print_ts("shardRestrict enabled but source shard not specified");
            print_ts("specify shard with setShard or disable shardRestrict");
            return 1;
        }
        if (this._shardRestrict && (! (this._destShard || this._destShards))){
            print_ts("shardRestrict enabled but destination shard(s) not specified");
            print_ts("specify shard(s) with setDestShard(s) or disable shardRestrict");
            return 2;
        }
        if (this._destShard && this._destShards){
            print_ts("cannot use both setDestShard and setDestShards, pick one");
            return 3;
        }

        var stars     = "********************************************************************";
        var estars    = "*                                                                  *";
        if (test){
            var title = "*                        THIS IS A TEST RUN                        *";
        } else {
            var title = "*                        THIS IS A REAL RUN                        *\n" +
                        "*                   You have 5 seconds to Ctrl-C                   *";
        }

        var nsString = "*  considering ns: ";
        
        if (this.namespace){
            nsString += this.namespace;
        } else {
            nsString += "all namespaces";
        }
        var padString = "*";
        for (var tmpi = stars.length; tmpi > nsString.length+1; tmpi--){
            padString = " "+padString;
        }
        nsString += padString;

        var crString = null;
        if (this._chunkRange){
            var crString = "*  considering only specified chunk range ";
            var padString = "*";
            for (var tmpi = stars.length; tmpi > crString.length+1; tmpi--){
                padString = " "+padString;
            }
            crString += padString;
        }

        var shardString = "*  from shard: ";
        if (this._shard){
            shardString += this._shard;
        } else {
            shardString += "all shards";
        }
        padString = "*";
        for (var tmpi = stars.length; tmpi > shardString.length+1; tmpi--){
            padString = " "+padString;
        }
        shardString += padString;

        destShardString = "*  to shard: ";
        if (this._destShard){
            destShardString += this._destShard;
        } else if (this._destShards){
            destShardString += this._destShards.toString();
        } else {
            destShardString += "whichever is thinnest at the time";
        }
        padString = "*";
        for (var tmpi = stars.length; tmpi > destShardString.length+1; tmpi--){
            padString = " "+padString;
        }
        destShardString += padString;

        if (this.sortBySmallest){
            var sortString= "*  chunks sorted smallest to largest";
        } else {
            var sortString= "*  chunks sorted largest to smallest";
        }
        padString = "*";
        for (var tmpi = stars.length; tmpi > sortString.length+1; tmpi--){
            padString = " "+padString;
        }
        sortString += padString;

        print(stars);
        print(estars);
        print(title)
        print(estars);
        print(nsString);
        if (crString){
            print(crString);
        }
        print(shardString);
        print(destShardString);
        print(sortString);
        print(estars);
        print(stars);

        if (! test){
            sleep(5000);
        }

        // disable the balancer
        if (test){
            print_ts("Disabling balancer (not really as this is a test)");
        } else {
            print_ts("Disabling balancer");
            assert.eq(this.disableBalancer(),1);
        }
        // find the chunks
        assert.eq(this.init(1),1);

        if (! this.chunks.length){
            print_ts("No chunks found, exiting");
            return 0;
        }

        var maxChunks;
        // lower expectations
        if ((this.chunks.length < this.maxChunks) || (this.maxChunks < 0)){
            maxChunks = this.chunks.length;
        } else {
            maxChunks = this.maxChunks;
        }

        // if we are moving chunks, consider all non-empty chunks
        // otherwise only process large chunks for splitting
        if (! this.move) {
            var lastLargeChunki = 0;
            for (var chunki = 0; chunki < this.chunks.length; chunki++){
                // find first chunk <= 64MB
                if (this.chunks[chunki].size/1024./1024. <= this.maxChunkSize)
                    break;
                else
                    lastLargeChunki++;
            }
            if (maxChunks > lastLargeChunki){
                maxChunks = lastLargeChunki;
            }
        }

        print_ts("Considering "+maxChunks+" chunks");
        var chunks = this.chunks.splice(0,maxChunks);

        // used to recalculate chunk distribution
        // in case of failed chunk move
        var recalc = false;
        // recalculate chunk distribution after n
        // successful chunk migrations
        var moves = 0;

        for (var chunki = 0; chunki < chunks.length; chunki++){
            // recalculate chunk distribution?
            if (recalc || (moves == 50)){
                if (! test){
                    print_ts("Recalculating chunk distribution...");
                    assert.eq(this.update(),1);
                } else {
                    print_ts("Recalculating chunk distribution (not really as this is a test)");
                }

                moves = 0;
                recalc = false;
            }

            // do not do first time through
            if (chunki){
                print_ts("Sleeping for "+this.sleep+" millis before starting chunk");
                // but not if we're testing because it's annoying
                if (! test){
                    sleep(this.sleep);
                }
            }

            var chunk = chunks[chunki];

            if (this.verbose){
                var pct = (chunki/chunks.length)*100;
                print_ts("Chunk "+parseInt(chunki+1)+" of "+chunks.length+" ("+pct.toPrecision(2)+"% complete):");
                printjson(chunk);
            } else {
                print_ts("Chunk {_id:'"+chunk.id+"'}");
            }

            var sizeInMB = chunk.size/1024./1024.;
            // Should we split the chunk?
            if (this.split && (sizeInMB > this.maxChunkSize)){
                // get array of splitKeys
                print_ts("Getting splitKeys for large chunk");
                var splitKeys = this.getSplitKeys(chunk);
                if (! splitKeys){
                    print_ts("Error getting splitKeys, skipping large chunk");
                    continue;
                } else {
                    if (this.verbose){
                        print_ts("Got splitKeys:");
                        printjson(splitKeys);
                    } else {
                        print_ts("Got splitKeys");
                    }

                    for (var spliti = 0; spliti < splitKeys.length; spliti++){
                        if (this._destShard){
                            var destinationShard = this._destShard;
                            var destinationString = "destination";
                        } else if (this._destShards){
                            // alternate between shards in _destShards
                            var destinationShard = this._destShards[(chunki % this._destShards.length)];
                            var destinationString = "destination";
                        } else {
                            var destinationShard = this.thinnestShard();
                            var destinationString = "thinnest";
                        }

                        if (this.verbose){
                            print_ts("Splitting at");
                            printjson(splitKeys[spliti]);
                        } else {
                            var lengthString = ""+splitKeys.length;
                            var splitiString = ""+(spliti+1);
                            var spacesString = "";
                            for (var tmpi = lengthString.length; tmpi > splitiString.length; tmpi--){
                                spacesString += " ";
                            }
                            print_ts("Splitting "+spacesString+splitiString+" of "+lengthString);
                        }

                        var chunkProj = splitKeys[spliti];
                        if (! test){
                            var res = this.splitChunk(chunk.ns, chunkProj);
                            if (! res){
                                // back to the chunki loop
                                break;
                            }
                        }

                        // splitKeys is where we split, but must move
                        // from chunk min
                        if (spliti == 0){
                            var theMin = chunk.min;
                        } else {
                            var theMin = splitKeys[spliti-1];
                        }

                        if (this.move) {
                            if (destinationShard == chunk.shard) {
                                print_ts("Already on "+destinationString+" shard, not moving");
                                continue;
                            } else {
                                if (this.verbose){
                                    print_ts("Moving chunk at");
                                    printjson(theMin);
                                    print_ts("to "+destinationShard);
                                } else {
                                    print_ts("Moving to "+destinationShard);
                                }

                                if (! test) {
                                    var res = this.moveChunk(chunk.ns, theMin, destinationShard);
                                    if (! res){
                                        recalc = true;
                                        // back to the chunki loop
                                        break;
                                    } else {
                                        moves++;
                                    }
                                }
                            }
                        }
                    } // spliti

                    // Don't forget to move the last split!
                    if (this.move) {
                        if (destinationShard == chunk.shard) {
                            print_ts("Already on "+destinationString+" shard, not moving");
                            continue;
                        } else {
                            var theMin = splitKeys[splitKeys.length-1];
                            if (this.verbose){
                                print_ts("Moving chunk at");
                                printjson(theMin);
                                print_ts("to "+destinationShard);
                            } else {
                                print_ts("Moving to "+destinationShard);
                            }

                            if (! test) {
                                var res = this.moveChunk(chunk.ns, theMin, destinationShard);
                            } else {
                                // simulate success
                                var res = true;
                            }

                            if (! res){
                                recalc = true;
                                // back to the chunki loop
                                break;
                            } else {
                                moves++;
                                // if we are here we moved the whole chunk successfully
                                // yay us! update shard sizes rather than recalculate
                                this.shards[chunk.shard].size -= chunk.size;
                                this.shards[destinationShard].size += chunk.size;
                            }
                        }
                    }
                }
            } else {
                // size is okay, try to move it
                if (this.move) {
                    if (this._destShard){
                        var destinationShard = this._destShard;
                        var destinationString = "destination";
                    } else if (this._destShards){
                        // alternate between shards in _destShards
                        var destinationShard = this._destShards[(chunki % this._destShards.length)];
                        var destinationString = "destination";
                    } else {
                        var destinationShard = this.thinnestShard();
                        var destinationString = "thinnest";
                    }
                    if (destinationShard == chunk.shard) {
                        print_ts("Already on "+destinationString+" shard, not moving");
                        continue;
                    } else {
                        if (this.verbose){
                            print_ts("Moving chunk at");
                            printjson(chunk.min);
                            print_ts("to "+destinationShard);
                        } else {
                            print_ts("Moving to "+destinationShard);
                        }

                        if (! test) {
                            var res = this.moveChunk(chunk.ns, chunk.min, destinationShard);
                        } else {
                            // simulate success
                            var res = true;
                        }

                        if (! res){
                            recalc = true;
                        } else {
                            moves++;
                            this.shards[chunk.shard].size -= chunk.size;
                            this.shards[destinationShard].size += chunk.size;
                        }
                    }
                }
            }
        } // chunki
    }, // run

    help: function(){
        print("");
        print("Balancer.setNamespace(string)      # only consider chunks in this namespace; default is all namespaces");
        print("Balancer.setShard(string)          # only consider chunks on this shard for splitting/moving; default is all shards");
        print("Balancer.setShardRestrict(bool)    # only consider chunks on shard specified with setShard for information gathering;");
        print("                                     if set, must also set source shard with setShard and destination shard with setDestShard(s)");
        print("                                     as we will not be able to determine which is the thinnest shard; default is all shards");
        print("Balancer.setChunkRange(first, last)# only consider chunks with min in the specified range; range is inclusive");
        print("                                     null first value is $minKey, null last value is $maxKey");
        print("Balancer.setDestShard(string)      # only move chunks to this shard; default is whichever shard is thinnest at the time");
        print("Balancer.setDestShards([string])   # alternate moving chunks to these shards only");
        print("Balancer.setMaxChunks(integer)     # maximum number of large chunks to process; default is all large chunks");
        print("Balancer.setMaxChunkSize(float)    # in MB, chunks larger than this will be split into chunks approximately");
        print("                                     half this size; default is 64");
        print("Balancer.setSortBySmallest(bool)   # consider chunks from smallest to largest; default is largest to smallest");
        print("Balancer.setSplit(boolean)         # split chunks larger than maxChunkSize; default is true");
        print("Balancer.setMove(boolean)          # move chunks to thinnest shard after splitting; default is false");
        print("Balancer.setSleepMS(integer)       # ms to sleep between processing of large chunks; default is 5000");
        print("Balancer.setVerbose(boolean)       # be loquacious");
        print("");
        print("Balancer.global.auth('user','pwd') # global auth parameters; note that user must have clusterAdmin role");
        print("Balancer.shard.auth('shard','user','pwd')");
        print("                                   # shard auth parameters; for the rare DBA who has different clusterAdmin");
        print("                                     users on different shards; Balancer.seeShrink() is deprecated");
        print("");
        print("Balancer.ready()                   # remove the safety; Balancer.run() will perform a real next time");
        print("Balancer.run()                     # do the work; if Balancer.ready() is called immediately before this");
        print("                                     the run will be REAL. Otherwise, it will be a test run.");
        print("");
    }
}

print("***                    Loaded balancer.js                     ***");
print("*** This is dangerous -- we are not responsible for data loss ***");
print("***    Run only on a mongos connected to a sharded cluster    ***");
print("***                                                           ***");
print("*** Balancer.help() <-- type that to get help                 ***");

