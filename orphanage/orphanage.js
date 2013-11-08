/*
 *
 * orphanage.js -- Utility to find and remove orphaned documents
 * 10gen 2012-2013 -- Tyler Brock, Scott Hernandez, Jacob Ribnik
 *
 * Script Orphan Finder Procedure:
 *  - Set up a connection to each shard
 *  - Turn off the balancer
 *  - For each chunk of data
 *    - Query each shard that is not in config
 *    - If the shard contains that chuck it is an orphan
 *  - Return a list of the orphan document counts for each {shard, chunk}
 *
 * Quick Sharding Setup:
 *  - var st = new ShardingTest({ shards: 2, mongos: 1 })
 *  - var st = new ShardingTest({ shards: 2, mongos: 1, other: { rs: true }})
 *  - var mongos = st.s
 *  - var shard0 = st.shard0
 *  - var shard1 = st.shard1
 *
 * Usage:
 *  - sh.stopBalancer()               -- Stop the balancer
 *  - Orphans.find('db.collection')   -- Find orphans in a given namespace
 *  - Orphans.findAll()               -- Find orphans in all namespaces
 *  - Orphans.remove()                -- Removes the next chunk
 *
 *  DISCLAIMER
 *
 *  Please note: all tools/ scripts in this repo are released for use "AS
 *  IS" without any warranties of any kind, including, but not limited to
 *  their installation, use, or performance. We disclaim any and all
 *  warranties, either express or implied, including but not limited to
 *  any warranty of noninfringement, merchantability, and/ or fitness for
 *  a particular purpose. We do not warrant that the technology will
 *  meet your requirements, that the operation thereof will be
 *  uninterrupted or error-free, or that any errors will be corrected.
 *
 *  Any use of these scripts and tools is at your own risk. There is no
 *  guarantee that they have been through thorough testing in a
 *  comparable environment and we are not responsible for any damage
 *  or data loss incurred with their use.
 *
 *  You are responsible for reviewing and testing any scripts you run
 *  thoroughly before use in any non-testing environment.
 */

// Orphanage object -- stores configuration and makes connections
var Orphanage = {
  globalAuthDoc: null,
  shardAuthDocs: {},
  global: {
    auth: (function(self){return function(user,pwd){
      self.Orphanage.globalAuthDoc = {'user':user,'pwd':pwd};
    }})(this)
  },
  shard: {
    auth: (function(self){return function(shard,user,pwd){
      self.Orphanage.shardAuthDocs[shard] = {'user':user,'pwd':pwd};
    }})(this)
  },
  copyDoc: function(doc){
    var newDoc = {};
    for (var prop in doc) {
      newDoc[prop] = doc[prop];
    }
    return newDoc;
  },
  shardConnection: function(shard){
    var conn = new Mongo(shard.host);
    var admin = conn.getDB("admin");

    // try shard specific auth first
    if (this.shardAuthDocs[shard._id]){
      // copy authDoc as we do not want auth
      // to modify the original SERVER-11626
      var authDoc = this.copyDoc(this.shardAuthDocs[shard._id]);

      // if that fails try global auth
      if (admin.auth(authDoc) != 1 && this.globalAuthDoc){
        authDoc = this.copyDoc(this.globalAuthDoc);
        admin.auth(authDoc);
      }
    } else if (this.globalAuthDoc){
      var authDoc = this.copyDoc(this.globalAuthDoc);
      admin.auth(authDoc);
    }
    return conn;
  }
}

// Shard object -- contains shard related functions
var Shard = {
  configDB: function() {return db.getSiblingDB("config");},
  active: [],
  // Returns an array of sharded namespaces
  namespaces: function(){
    var nsl = [] // namespace list
    this.configDB().collections.find().forEach(function(ns){nsl.push(ns._id)})
    return nsl
  },

  // Returns map of shard names -> shard connections
  connections: function() {
    var conns = {}
    this.configDB().shards.find().forEach( function (shard) {
        // skip inactive shards (use can specify active shards)
        if (Shard.active && Shard.active.length > 0 && !Array.contains(Shard.active, shard._id))
            return;
        conns[shard._id] = Orphanage.shardConnection(shard);
    });
    return conns;
  }
}

// Orphans object -- finds and removes orphaned documents
var Orphans = {
  find: function(namespace) {
    // Make sure this script is being run on mongos
    assert(Shard.configDB().runCommand({ isdbgrid: 1}).ok, "Not a sharded cluster")

    assert(!sh.isBalancerRunning(), "Balancer must be stopped first")
    print("Searching for orphans in namespace [" + namespace + "]")
    var shardConns = Shard.connections()
    var connections = {};

    // skip shards that have no data yet
    for(shard in shardConns) {
        if (shardConns[shard].getCollection(namespace).count() > 0)
            connections[shard] = shardConns[shard];
    }

    var result = {
      badChunks: [],
      count: 0,
      shardCounts:{},
      hasNext: function(){
        if (this.badChunks.length > 0) { return true }
        else { return false }
      },
      next: function() {
        bchunk = this.badChunks[0]
//        print("Calling Orphans.remove() will remove " + bchunk.orphanCount +
//              " orphans from chunk " + bchunk._id + " on " + bchunk.orphanedOn)
//        print("Documents for this chunk should only exist on " + bchunk.shard)
      },
      remove: function() {
        var bchunk = this.badChunks.splice(0,1)[0]
        print("Removing orphaned chunk " + bchunk._id + " from " + bchunk.orphanedOn)
        var naCollection = connections[bchunk.orphanedOn].getCollection(namespace)
        var toRemove = naCollection.find({}, {_id: 1}).min(bchunk.min).max(bchunk.max)
        var idsToRemove = []

        while (toRemove.hasNext()) {
          idsToRemove.push(toRemove.next()._id)
        }

        naCollection.remove({ _id: { $in: idsToRemove } })

        if (error = naCollection.getDB().getLastError()) {
          print("-> There was an error: " + error)
        } else {
          print("-> Sucessfully removed " + idsToRemove.length + " orphaned documents from " + namespace)
        }
        return idsToRemove.length
      },
      removeAll: function(secs) {
          var num = 0;
          while (this.hasNext()) {
            num += this.remove()
            if(secs)
                sleep(secs * 1000);
          }
          return num;
      }
    }


    // iterate over chunks -- only one shard should own each chunk
    Shard.configDB().chunks.find({ ns: namespace }).batchSize(5).forEach( function(chunk) {
      // query all non-authoritative shards
      for (var shard in connections) {
        if (shard != chunk.shard) {
          // make connection to non-authoritative shard
          var naCollection = connections[shard].getCollection(namespace)

          // gather documents that should not exist here
          var orphanCount = naCollection.find()._addSpecial("$returnKey", true).min(chunk.min).max(chunk.max).itcount();

          if (orphanCount > 0) {
            result.count += orphanCount

            // keep count by shard
            if(!result.shardCounts[shard])
                result.shardCounts[shard] = orphanCount;
            else
                result.shardCounts[shard] += orphanCount;

            chunk.orphanedOn = shard
            chunk.orphanCount = orphanCount
            result.badChunks.push(chunk)
          }
        }
      }
    });

    if (result.count > 0) {
      print("-> " + result.count + " orphan(s) found in " + result.badChunks.length +
            " chunks(s) in namespace [" + namespace + "]\n\tOrphans by Shard:")
      print("\t\t" + tojson(result.shardCounts));
      print("");
    } else {
      print("-> No orphans found in [" + namespace  + "]\n")
    }
    return result
  },
  findAll: function(){
    var result = {}
    var namespaces = Shard.namespaces()

    for (i in namespaces) {
      namespace = namespaces[i];
      result[namespace] = this.find(namespace);
    }
    return result;
  },
  // Remove all orphaned chunks
  removeAll: function(nsMap) {
      var num = 0;
      if(nsMap)
          for(ns in nsMap)
              num += nsMap[ns].removeAll();

      return num;
  }
}

print("***                    Loaded orphanage.js                    ***")
print("*** This is dangerous -- we are not responsible for data loss ***")
print("***    Run only on a mongos connected to a sharded cluster    ***")
print("")
print("usage:")
print("Orphanage.global.auth('username','password') -- Set global authentication parameters")
print("Orphanage.shard.auth('shard','username','password') -- Set shard authentication parameters")
print("Shard.active = \[\"shard1\",\"shard2\"\]-- Specify active shards (they will be used for finding orphans)")
print("Orphans.find('db.collection')     -- Find orphans in a given namespace")
print("Orphans.findAll()                 -- Find orphans in all namespaces")
print("Orphans.removeAll(findAllResults) -- Removes orphans in all namespaces")
print("")
print("To remove orphaned documents:")
print("var result = Orphans.find('db.collection')")
print("result.hasNext()                  -- Returns true if ns has more bad chunks")
print("result.next()                     -- Shows information about the next chunk")
print("result.remove()                   -- Removes the next chunk")
print("")
