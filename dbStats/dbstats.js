/*
 *  Name: "dbstats.js"
 *  Version: "0.12.1"
 *  Description: "MongoDB storage statistics script"
 *  Authors: ["Luke Prochazka <luke.prochazka@mongodb.com>"]
 */

// Usage: [mongo|mongosh] [connection options] --quiet [--eval 'let options = {...};'] [-f|--file] dbstats.js

/*
 *  options = {
 *     filter: {
 *        db: <null|<string>|/<regex>/>,
 *        collection: <null|<string>|/<regex>/>
 *     },
 *     sort: {
 *        db: {
 *           name: <1|0|-1>,
 *           dataSize: <1|0|-1>,
 *           storageSize: <1|0|-1>,
 *           freeStorageSize: <1|0|-1>,
 *           idxStorageSize: <1|0|-1>, // TBA
 *           freeStorageSize: <1|0|-1>,
 *           idxFreeStorageSize: <1|0|-1>, // TBA
 *           reuse: <1|0|-1>, // TBA
 *           idxReuse: <1|0|-1>, // TBA
 *           compaction: <1|0|-1>, // TBA
 *           compression: <1|0|-1>, // TBA
 *           objects: <1|0|-1>
 *        },
 *        collection: {
 *           name: <1|0|-1>,
 *           dataSize: <1|0|-1>,
 *           storageSize: <1|0|-1>,
 *           freeStorageSize: <1|0|-1>,
 *           reuse: <1|0|-1>, // TBA
 *           compaction: <1|0|-1>, // TBA
 *           compression: <1|0|-1>, // TBA
 *           objects: <1|0|-1>
 *        },
 *        view: {
 *           name: <1|0|-1>
 *        },
 *        namespace: {
 *           namespace: <1|0|-1>,
 *           dataSize: <1|0|-1>,
 *           storageSize: <1|0|-1>,
 *           freeStorageSize: <1|0|-1>,
 *           reuse: <1|0|-1>,
 *           compaction: <1|0|-1>,
 *           compression: <1|0|-1>,
 *           objects: <1|0|-1>
 *        },
 *        index: {
 *           name: <1|0|-1>,
 *           idxDataSize: <1|0|-1>, // TBA (inferred from "storageSize - freeStorageSize")
 *           idxStorageSize: <1|0|-1>,
 *           idxFreeStorageSize: <1|0|-1>,
 *           reuse: <1|0|-1>, // TBA
 *           compaction: <1|0|-1> // TBA
 *        }
 *     },
 *     limit: { // TBA
 *        dataSize: <int>,
 *        storageSize: <int>,
 *        freeStorageSize: <int>,
 *        reuse: <int>,
 *        compression: <int>,
 *        objects: <int>
 *     },
 *     output: {
 *        format: <'table'|'nsTable'|'json'|'html'>,
 *        topology: <'summary'|'expanded'>, // TBA
 *        colour: <true|false>, // TBA
 *        verbosity: <'full'|'summary'|'summaryIdx'|'compactOnly'/> // TBA
 *     },
 *     topology: { // TBA
 *        discover: <true|false>,
 *        replica: <'summary'|'expanded'>,
 *        sharded: <'summary'|'expanded'>
 *     }
 *  }
 */

/*
 *  Examples of using filters with namespace regex:
 *
 *    mongosh --quiet --eval 'let options = { filter: { db: "^database$" } };' -f dbstats.js
 *    mongosh --quiet --eval 'let options = { filter: { collection: "^c.+" } };' -f dbstats.js
 *    mongosh --quiet --eval 'let options = { filter: { db: /(^(?!(d.+)).+)/i, collection: /collection/i } };' -f dbstats.js
 *
 *  Examples of using sorting:
 *
 *    mongosh --quiet --eval 'let options = { sort: { collection: { dataSize: -1 }, index: { idxStorageSize: -1 } } };' -f dbstats.js
 *    mongosh --quiet --eval 'let options = { sort: { collection: { freeStorageSize: -1 }, index: { idxFreeStorageSize: -1 } } };' -f dbstats.js
 *
 *  Examples of using formatting:
 *
 *    mongosh --quiet --eval 'let options = { output: { format: "tabular" } };' -f dbstats.js
 *    mongosh --quiet --eval 'let options = { output: { format: "json" } };' -f dbstats.js
 */

/*
 *  Load helper mdblib.js (https://github.com/tap1r/mongodb-scripts/blob/master/src/mdblib.js)
 *  Save libs to the $MDBLIB or other valid search path
 */

(() => {
   const __script = { "name": "dbstats.js", "version": "0.12.1" };
   if (typeof __lib === 'undefined') {
      /*
       *  Load helper library mdblib.js
       */
      let __lib = { "name": "mdblib.js", "paths": null, "path": null };
      if (typeof _getEnv !== 'undefined') { // newer legacy shell _getEnv() method
         __lib.paths = [_getEnv('MDBLIB'), `${_getEnv('HOME')}/.mongodb`, '.'];
         __lib.path = `${__lib.paths.find(path => fileExists(`${path}/${__lib.name}`))}/${__lib.name}`;
      } else if (typeof process !== 'undefined') { // mongosh process.env attribute
         __lib.paths = [process.env.MDBLIB, `${process.env.HOME}/.mongodb`, '.'];
         __lib.path = `${__lib.paths.find(path => fs.existsSync(`${path}/${__lib.name}`))}/${__lib.name}`;
      } else {
         print(`[WARN] Legacy shell methods detected, must load ${__lib.name} from the current working directory`);
         __lib.path = __lib.name;
      }
      load(__lib.path);
   }
   let __comment = `#### Running script ${__script.name} v${__script.version}`;
   __comment += ` with ${__lib.name} v${__lib.version}`;
   __comment += ` on shell v${version()}`;
   // console.clear();
   console.log(`\n\n[yellow]${__comment}[/]`);
   if (shellVer() < serverVer() && typeof process === 'undefined') console.log(`\n[red][WARN] Possibly incompatible legacy shell version detected: ${version()}[/]`);
   if (shellVer() < 1.0 && typeof process !== 'undefined') console.log(`\n[red][WARN] Possible incompatible non-GA shell version detected: ${version()}[/]`);
   if (serverVer() < 4.2) console.log(`\n[red][ERROR] Unsupported mongod/s version detected: ${db.version()}[/]`);
})();

(() => {
   /*
    *  Ensure authorized users have the following minimum required roles
    *  clusterMonitor@admin && readAnyDatabase@admin
    */
   try {
      db.adminCommand({ "features": 1 });
   } catch({ codeName }) {
      if (codeName == 'Unauthorized') {
         console.log('[red][ERR] MongoServerError: Unauthorized user requires authentication[/]');
      }
   }
   const monitorRoles = ['clusterMonitor'],
         adminRoles = ['atlasAdmin', 'clusterAdmin', 'backup', 'root', '__system'],
         dbRoles = ['dbAdminAnyDatabase', 'readAnyDatabase', 'readWriteAnyDatabase'];
   const { 'authInfo': { authenticatedUsers, authenticatedUserRoles } } = db.adminCommand({ "connectionStatus": 1 });
   const authz = authenticatedUserRoles.filter(({ role, db }) => dbRoles.includes(role) && db == 'admin'),
         users = authenticatedUserRoles.filter(({ role, db }) => adminRoles.includes(role) && db == 'admin'),
         monitors = authenticatedUserRoles.filter(({ role, db }) => monitorRoles.includes(role) && db == 'admin');
   if (!(!(!!authenticatedUsers.length) || !!users.length || !!monitors.length && !!authz.length)) {
      console.log(`[red][WARN] The connecting user's authz privileges may be inadequate to report all namespaces statistics[/]`);
      console.log(`[red][WARN] consider inheriting the built-in roles for 'clusterMonitor@admin' and 'readAnyDatabase@admin' at a minimum[/]`);
   }
})();

// (async(db, options, dbstats = {}) => {
(async() => {
   /*
    *  User defined parameters
    */
   const optionsDefaults = {
      "filter": {
         "db": new RegExp(/.+/),
         "collection": new RegExp(/.+/)
      },
      "sort": {
         "db": {
            "name": 0,
            "dataSize": 0,
            "storageSize": 0,
            "idxStorageSize": 0, // TBA
            "freeStorageSize": 0,
            "idxFreeStorageSize": 0, // TBA
            "reuse": 0, // TBA
            "idxReuse": 0, // TBA
            "compression": 0,
            "objects": 0,
            "compaction": 0 // TBA
         },
         "collection": {
            "name": 0,
            "dataSize": 0,
            "storageSize": 0,
            "freeStorageSize": 0,
            "reuse": 0, // TBA
            "compression": 0,
            "objects": 0,
            "compaction": 0 // TBA
         },
         "view": {
            "name": 1
         },
         "namespace": {
            "name": 0, // do not use
            "namespace": 0,
            "dataSize": 0,
            "storageSize": 0,
            "freeStorageSize": 0,
            "reuse": 0, // TBA
            "compression": 0, // TBA
            "objects": 0,
            "compaction": 0 // TBA
         },
         "index": {
            "name": 0,
            "idxDataSize": 0, // TBA (inferred from "storageSize - freeStorageSize")
            "idxStorageSize": 0,
            "idxFreeStorageSize": 0,
            "reuse": 0, // TBA
            "compaction": 0 // TBA
         }
      },
      "limit": { // TBA
         "dataSize": 0,
         "storageSize": 0,
         "freeStorageSize": 0,
         "reuse": 0,
         "compression": 0,
         "objects": 0
      },
      "output": {
         "format": "tabular", // ['tabular'|'nsTable'|'json'|'html']
         "topology": "summary", // ['summary'|'expanded'] // TBA
         "colour": true, // [true|false] // TBA
         "verbosity": "full" // ['full'|'summary'|'summaryIdx'|'compactOnly'] // TBA
      },
      "topology": { // TBA
         "discover": true, // [true|false]
         "replica": "summary", // ['summary'|'expanded']
         "sharded": "summary" // ['summary'|'expanded']
      }
   };
   typeof options === 'undefined' && (options = optionsDefaults);
   const filterOptions = { ...optionsDefaults.filter, ...options.filter };
   const sortOptions = { ...optionsDefaults.sort, ...options.sort };
   const outputOptions = { ...optionsDefaults.output, ...options.output };
   // const limitOptions = { ...optionsDefaults.limit, ...options.limit };
   // const topologyOptions = { ...optionsDefaults.topology, ...options.topology };

   /*
    *  Global defaults
    */

   // scalar unit B, KiB, MiB, GiB, TiB, PiB
   const scaled = new AutoFactor();

   // formatting preferences
   typeof termWidth === 'undefined' && (termWidth = 137) || termWidth;
   typeof columnWidth === 'undefined' && (columnWidth = 14) || columnWidth;
   typeof rowHeader === 'undefined' && (rowHeader = 40) || rowHeader;

   // connection preferences
   typeof readPref === 'undefined' && (readPref = (hello().secondary) ? 'secondaryPreferred' : 'primaryPreferred');

   async function main() {
      /*
       *  main
       */
      const { 'format': formatOutput = 'tabular' } = outputOptions;

      slaveOk(readPref);
      const dbStats = await getStats();

      switch (formatOutput) {
         case 'json':
            // jsonOut(dbStats);
            return dbStats;
            // dbStats
            // break;
         case 'html':
            htmlOut(dbStats);
            break;
         case 'nsTable':
            nsTableOut(dbStats);
            break;
         default: // tabular
            tableOut(dbStats);
      }

      return;
   }

   async function getStats() {
      /*
       *  Gather DB stats
       */
      let { 'db': dbFilter, 'collection': collFilter } = filterOptions;
      collFilter = new RegExp(collFilter);
      const systemFilter = /.+/;
      let dbPath = new MetaStats();
      dbPath.init();
      if (dbPath.shards.length > 0) {
         const paddedArray = [...Array(dbPath.shards.length)].map(() => 0);
         dbPath.ncollections = paddedArray;
         dbPath.nviews = paddedArray;
         dbPath.namespaces = paddedArray;
         dbPath.indexes = paddedArray;
      }
      delete dbPath.name;
      delete dbPath.collections;
      delete dbPath.views;
      // delete dbPath.indexes;
      // delete dbPath.nindexes;
      delete dbPath.compressor;

      const dbNames = (shellVer() >= 2.0 && typeof process !== 'undefined')
                    ? getDBNames(dbFilter).toSorted(sortAsc) // mongosh v2 optimised
                    : getDBNames(dbFilter).sort(sortAsc);    // legacy shell(s) method
      console.log('');
      // add debug clause
      // if (dbPath.shards.length > 0) {
      //    console.log('Discovered', dbPath.shards.length, 'shards:', JSON.stringify(dbPath.shards, null, 3));
      // }
      // console.log('Discovered', dbNames.length, 'distinct databases');
      // const dbFetchTasks = dbNames.map(async dbName => {
      dbPath.databases = dbNames.map(dbName => {
         let database = new MetaStats($stats(dbName));
         delete database.databases;
         delete database.instance;
         delete database.hostname;
         delete database.proc;
         delete database.dbPath;
         database.shards = dbPath.shards;
         if (dbPath.shards.length > 0) {
            dbPath.ncollections = dbPath.ncollections.reduce((result, current, _idx) => {
                  result.push(current + database.ncollections[_idx]);
                  return result;
               }, []);
            dbPath.nviews = dbPath.nviews.reduce((result, current, _idx) => {
                  result.push(current + database.nviews[_idx]);
                  return result;
               }, []);
            dbPath.namespaces = dbPath.namespaces.reduce((result, current, _idx) => {
                  result.push(current + database.namespaces[_idx]);
                  return result;
               }, []);
            dbPath.indexes = dbPath.indexes.reduce((result, current, _idx) => {
                  result.push(current + database.indexes[_idx]);
                  return result;
               }, []);
            dbPath.nindexes = dbPath.indexes;
         } else {
            dbPath.ncollections += database.ncollections;
            dbPath.nviews += database.nviews;
            dbPath.namespaces += database.namespaces;
            // dbPath.indexes += +database.indexes;
            dbPath.nindexes += +database.indexes;
         }
         dbPath.dataSize += database.dataSize;
         dbPath.storageSize += database.storageSize;
         dbPath.freeStorageSize += database.freeStorageSize;
         dbPath.objects += database.objects;
         dbPath.orphans += database.orphans;
         dbPath.totalIndexSize += database.totalIndexSize;
         dbPath.totalIndexBytesReusable += database.totalIndexBytesReusable;

         return database;
      });
      // dbPath.databases = await Promise.all(dbFetchTasks);

      // add debug clause
      // if (dbPath.shards.length > 0) {
      //    console.log(
      //       'Discovered distributed namespaces:',
      //       JSON.stringify(
      //          dbPath.shards.map((shard, _i) => {
      //             return { [shard]: dbPath.namespaces[_i] }
      //          }), null, 3
      //       ).replace(/(?<![\[])(?:\n\s+)/g, ' '); // legacy shell doesn't support this
      //    );
      //    console.log(
      //       'Discovered distributed indexes:',
      //       JSON.stringify(
      //          dbPath.shards.map((shard, _i) => {
      //             return { [shard]: dbPath.nindexes[_i] }
      //          }), null, 3
      //       ).replace(/(?<![\[])(?:\n\s+)/g, ' '); // legacy shell doesn't support this
      //    );
      // } else {
      //    console.log('Discovered', dbPath.namespaces, 'distinct namespaces');
      //    console.log('Discovered', dbPath.nindexes, 'distinct indexes');
      // }

      let collNamesTasks = dbPath.databases.map(async database => {
         database.collections = (shellVer() >= 2.0 && typeof process !== 'undefined')
            ? db.getSiblingDB(database.name).getCollectionInfos({ // mongosh v2 optimised
                  "type": /^(collection|timeseries)$/,
                  "name": collFilter
               },
               { "nameOnly": true },
               true
              ).filter(({ 'name': collName }) => collName.match(systemFilter)).toSorted(sortNameAsc)
            : db.getSiblingDB(database.name).getCollectionInfos({ // legacy shell(s) method
                  "type": /^(collection|timeseries)$/,
                  "name": collFilter
               },
               (typeof process !== 'undefined') ? { "nameOnly": true } : true,
               true
              ).filter(({ 'name': collName }) => collName.match(systemFilter)).sort(sortNameAsc);
         database.views = (shellVer() >= 2.0 && typeof process !== 'undefined')
            ? db.getSiblingDB(database.name).getCollectionInfos({ // mongosh v2 optimised
                  "type": "view",
                  "name": collFilter
               },
               { "nameOnly": true },
               true
              ).toSorted(sortBy('view'))
              // ).filter(({ 'name': viewName }) => viewName.match(systemFilter)).toSorted(sortBy('view'))
            : db.getSiblingDB(database.name).getCollectionInfos({ // legacy shell(s) method
                  "type": "view",
                  "name": collFilter
               },
               (typeof process !== 'undefined') ? { "nameOnly": true } : true,
               true
              ).sort(sortBy('view'));
              // ).filter(({ 'name': viewName }) => viewName.match(systemFilter)).sort(sortBy('view'));

         return database;
      });
      dbPath.databases = await Promise.all(collNamesTasks);

      const dbFetchTasks = dbPath.databases.map(async database => {
         const collFetchTasks = database.collections.map(async({ 'name': collName }) => {
            let collection = new MetaStats($collStats(database.name, collName));
            delete collection.databases;
            delete collection.collections;
            delete collection.views;
            delete collection.ncollections;
            delete collection.nviews;
            delete collection.namespaces;
            delete collection.instance;
            delete collection.hostname;
            delete collection.proc;
            delete collection.dbPath;
            // collection.indexes.sort(sortBy('index')); // add toSorted optimisation here
            collection.indexes = (shellVer() >= 2.0 && typeof process !== 'undefined')
               ? collection.indexes.toSorted(sortBy('index')) // mongosh v2 optimised
               : collection.indexes.sort(sortBy('index'));    // legacy shell(s) method

            return collection;
         });
         database.collections = await Promise.all(collFetchTasks);
         // database.collections.sort(sortBy('collection')); // add toSorted optimisation here
         database.collections = (shellVer() >= 2.0 && typeof process !== 'undefined')
            ? database.collections.toSorted(sortBy('collection')) // mongosh v2 optimised
            : database.collections.sort(sortBy('collection'));    // legacy shell(s) method
         database.views = db.getSiblingDB(database.name).getCollectionInfos({
               "type": "view",
               "name": collFilter
            },
            (typeof process !== 'undefined') ? { "nameOnly": true } : true,
            true
         ); // .sort(sortBy('view')); // add toSorted optimisation here
         database.views = (shellVer() >= 2.0 && typeof process !== 'undefined')
            ? database.views.toSorted(sortBy('view')) // mongosh v2 optimised
            : database.views.sort(sortBy('view'));    // legacy shell(s) method
         dbPath.databases = (shellVer() >= 2.0 && typeof process !== 'undefined')
            ? dbPath.databases.toSorted(sortBy('db')) // mongosh v2 optimised
            : dbPath.databases.sort(sortBy('db'));    // legacy shell(s) method

         return database;
      });
      dbPath.databases = await Promise.all(dbFetchTasks);
      dbPath.databases = (shellVer() >= 2.0 && typeof process !== 'undefined')
         ? dbPath.databases.toSorted(sortBy('db')) // mongosh v2 optimised
         : dbPath.databases.sort(sortBy('db'));    // legacy shell(s) method

      return dbPath;
   }

   function tableOut(dbStats = {}) {
      /*
       *  Print plain tabular report
       */
      dbStats.databases.forEach(database => {
         printDbHeader(database);
         printCollHeader(database.collections.length);
         database.collections.forEach(collection => {
            printCollection(collection);
            collection.indexes.forEach(printIndex);
         });
         printViewHeader(database.views.length);
         database.views.forEach(({ name }) => printView(name));
         printDb(database);
      });
      printDbPath(dbStats);

      return;
   }

   function nsTableOut(dbStats = {}) {
      /*
       *  Print aggregated namespaces tabular report
       */
      const namespaces = dbStats.databases.flatMap(database => {
         return database.collections.reduce((collections, collection) => {
            const namespace = database.name + '.' + collection.name;
            delete collection.name;
            const updatedCollection = { ...{ "namespace": namespace }, ...collection, ...{ compression: 0 }
            // , ...{ get compression() {
            //    return this.dataSize / (this.storageSize - this.freeStorageSize);
            // } }
            };
            collections.push(updatedCollection);
            return collections;
         }, []);
      }).sort(sortBy('namespace'));

      printNSHeader(namespaces.length);
      namespaces.forEach(namespace => {
         printNamespace(namespace);
         namespace.indexes.forEach(printIndex);
      });
      printDbPath(dbStats);

      return;
   }

   function jsonOut(dbStats = {}) {
      /*
       *  JSON out
       */
      console.log('');
      printjson(dbStats);

      return;
   }

   function htmlOut(dbStats = {}) {
      /*
       *  HTML out
       */
      console.log('HTML support TBA');

      return;
   }

   function sortBy(type) {
      /*
       *  sortBy value
       */
      const sortByType = sortOptions[type];
      const sortKey = Object.keys(sortByType).find(key => sortByType[key] !== 0) || 'name';
      let sortValue = sortByType[sortKey];
      switch (sortValue) {
         case -1:
            sortValue = 'desc';
            break;
         default:
            sortValue = 'asc';
      }

      const sortFns = {
         "sort": {
            "asc": sortAsc,
            "desc": sortDesc
         },
         "name": {
            "asc": sortNameAsc,
            "desc": sortNameDesc
         },
         "namespace": {
            "asc": sortNamespaceAsc,
            "desc": sortNamespaceDesc
         },
         "dataSize": {
            "asc": sortDataSizeAsc,
            "desc": sortDataSizeDesc
         },
         "storageSize": {
            "asc": storageSizeAsc,
            "desc": storageSizeDesc
         },
         "freeStorageSize": {
            "asc": sortFreeStorageSizeAsc,
            "desc": sortFreeStorageSizeDesc
         },
         "idxDataSize": {
            "asc": sortIdxDataSizeAsc,
            "desc": sortIdxDataSizeDesc
         },
         "idxStorageSize": {
            "asc": sortIdxStorageSizeAsc,
            "desc": sortIdxStorageSizeDesc
         },
         "idxFreeStorageSize": {
            "asc": sortIdxFreeStorageSizeAsc,
            "desc": sortIdxFreeStorageSizeDesc
         },
         "reuse": { // TBA
            "asc": sortAsc,
            "desc": sortDesc
         },
         "compression": { // TBA
            "asc": sortAsc,
            "desc": sortDesc
         },
         "objects": {
            "asc": sortObjectsAsc,
            "desc": sortObjectsDesc
         },
         "compaction": { // TBA
            "asc": sortAsc,
            "desc": sortDesc
         }
      };

      return sortFns[sortKey][sortValue];
   }

   function sortAsc(x, y) {
      /*
       *  sort by value ascending
       */
      return x.localeCompare(y);
   }

   function sortDesc(x, y) {
      /*
       *  sort by value descending
       */
      return y.localeCompare(x);
   }

   function sortNameAsc(x, y) {
      /*
       *  sort by name ascending
       */
      return x.name.localeCompare(y.name);
   }

   function sortNameDesc(x, y) {
      /*
       *  sort by name descending
       */
      return y.name.localeCompare(x.name);
   }

   function sortNamespaceAsc(x, y) {
      /*
       *  sort by namespace ascending
       */
      return x.namespace.localeCompare(y.namespace);
   }

   function sortNamespaceDesc(x, y) {
      /*
       *  sort by namespace descending
       */
      return y.namespace.localeCompare(x.namespace);
   }

   function sortDataSizeAsc(x, y) {
      /*
       *  sort by dataSize ascending
       */
      return x.dataSize - y.dataSize;
   }

   function sortDataSizeDesc(x, y) {
      /*
       *  sort by dataSize descending
       */
      return y.dataSize - x.dataSize;
   }

   function sortIdxStorageSizeAsc(x, y) {
      /*
       *  sort by index dataSize ascending
       */
      return x.storageSize - y.storageSize;
   }

   function sortIdxStorageSizeDesc(x, y) {
      /*
       *  sort by index dataSize descending
       */
      return y.storageSize - x.storageSize;
   }

   function sortIdxDataSizeAsc(x, y) {
      /*
       *  sort by index "dataSize" ascending
       */
      return x.storageSize - x.freeStorageSize - y.storageSize - y.freeStorageSize;
   }

   function sortIdxDataSizeDesc(x, y) {
      /*
       *  sort by index "dataSize" descending
       */
      return y.storageSize - y.freeStorageSize - x.storageSize - x.freeStorageSize;
   }

   function sortIdxFreeStorageSizeAsc(x, y) {
      /*
       *  sort by index freeStorageSize ascending
       */
      return x.freeStorageSize - y.freeStorageSize;
   }

   function sortIdxFreeStorageSizeDesc(x, y) {
      /*
       *  sort by index freeStorageSize descending
       */
      return y.freeStorageSize - x.freeStorageSize;
   }

   function storageSizeAsc(x, y) {
      /*
       *  sort by 'file size in bytes' ascending
       */
      return x.storageSize - y.storageSize;
   }

   function storageSizeDesc(x, y) {
      /*
       *  sort by 'file size in bytes' descending
       */
      return y.storageSize - x.storageSize;
   }

   function sortFreeStorageSizeAsc(x, y) {
      /*
       *  sort by 'file bytes available for reuse' ascending
       */
      return x.freeStorageSize - y.freeStorageSize;
   }

   function sortFreeStorageSizeDesc(x, y) {
      /*
       *  sort by 'file bytes available for reuse' descending
       */
      return y.freeStorageSize - x.freeStorageSize;
   }

   function sortObjectsAsc(x, y) {
      /*
       *  sort by objects/document count ascending
       */
      return x.objects - y.objects;
   }

   function sortObjectsDesc(x, y) {
      /*
       *  sort by objects/document count descending
       */
      return y.objects - x.objects;
   }

   function formatUnit(metric) {
      /*
       *  Pretty format unit
       */
      return scaled.format(metric);
   }

   function formatPct(numerator = 0, denominator = 1) {
      /*
       *  Pretty format percentage
       */
      return `${Number.parseFloat(((numerator / denominator) * 100).toFixed(1))}%`;
   }

   function formatRatio(metric) {
      /*
       *  Pretty format ratio
       */
      return `${Number.parseFloat(metric.toFixed(2))}:1`;
   }

   function printCollHeader(collTotal = 0) {
      /*
       *  Print collection table header
       */
      console.log(`[yellow]${'━'.repeat(termWidth)}[/]`);
      console.log(`[bold][green]Collections:[/]${' '.repeat(1)}${collTotal}`);

      return;
   }

   function printNSHeader(nsTotal = 0) {
      /*
       *  Print namespace table header
       */
      console.log('');
      console.log(`[yellow]${'═'.repeat(termWidth)}[/]`);
      console.log(`[bold][green]${`Namespaces:[/]${' '.repeat(1)}${nsTotal}`.padEnd(rowHeader + 4)}[/] [bold][green]${'Data size'.padStart(columnWidth)} ${'Compression'.padStart(columnWidth + 1)} ${'Size on disk'.padStart(columnWidth)} ${'Free blocks | reuse'.padStart(columnWidth + 8)} ${'Object count'.padStart(columnWidth)}${'Compaction'.padStart(columnWidth - 1)}[/]`);

      return;
   }

   function printCollection({ name, dataSize, compression, compressor, storageSize, freeStorageSize, objects } = {}) {
      /*
       *  Print collection level stats
       */
      compressor = (compressor == 'snappy') ? 'snpy' : compressor;
      const collWidth = rowHeader - 3;
      const compaction = (name == 'oplog.rs' && compactionHelper('collection', storageSize, freeStorageSize)) ? 'wait'
                     : compactionHelper('collection', storageSize, freeStorageSize) ? 'compact'
                     : '--  ';
      console.log(`[yellow]${'━'.repeat(termWidth)}[/]`);
      if (name.length > 45) name = `${name.substring(0, collWidth)}~`;
      console.log(`└[cyan]${(' ' + name).padEnd(rowHeader - 1)}[/] ${formatUnit(dataSize).padStart(columnWidth)} ${(formatRatio(compression) + (compressor).padStart(compressor.length + 1)).padStart(columnWidth + 1)} ${formatUnit(storageSize).padStart(columnWidth)} ${(formatUnit(freeStorageSize) + ' |' + (formatPct(freeStorageSize, storageSize)).padStart(6)).padStart(columnWidth + 8)} ${objects.toString().padStart(columnWidth)} [cyan]${compaction.padStart(columnWidth - 2)}[/]`);

      return;
   }

   function printNamespace({ namespace, dataSize, compression, compressor, storageSize, freeStorageSize, objects } = {}) {
      /*
       *  Print namespace level stats
       */
      compressor = (compressor == 'snappy') ? 'snpy' : compressor;
      const collWidth = rowHeader - 3;
      const compaction = (namespace == 'local.oplog.rs' && compactionHelper('collection', storageSize, freeStorageSize)) ? 'wait'
                       : compactionHelper('collection', storageSize, freeStorageSize) ? 'compact'
                       : '--  ';
      console.log(`[yellow]${'━'.repeat(termWidth)}[/]`);
      if (namespace.length > 45) namespace = `${namespace.substring(0, collWidth)}~`;
      console.log(`└[cyan]${(' ' + namespace).padEnd(rowHeader - 1)}[/] ${formatUnit(dataSize).padStart(columnWidth)} ${(formatRatio(compression) + (compressor).padStart(compressor.length + 1)).padStart(columnWidth + 1)} ${formatUnit(storageSize).padStart(columnWidth)} ${(formatUnit(freeStorageSize) + ' |' + (formatPct(freeStorageSize, storageSize)).padStart(6)).padStart(columnWidth + 8)} ${objects.toString().padStart(columnWidth)} [cyan]${compaction.padStart(columnWidth - 2)}[/]`);

      return;
   }

   function printViewHeader(viewTotal = 0) {
      /*
       *  Print view table header
       */
      console.log(`[yellow]${'━'.repeat(termWidth)}[/]`);
      console.log(`[bold][green]Views:[/] ${viewTotal}`);

      return;
   }

   function printView(viewName = 'unknown') {
      /*
       *  Print view name
       */
      console.log(`[yellow]${'━'.repeat(termWidth)}[/]`);
      console.log(` [cyan]${viewName}[/]`);

      return;
   }

   function printIndex({ name, storageSize, freeStorageSize } = {}) {
      /*
       *  Print index level stats
       */
      const indexWidth = rowHeader + columnWidth * 2;
      const compaction = (name == '_id_' && compactionHelper('index', storageSize, freeStorageSize)) ? 'compact()'
                     : compactionHelper('index', storageSize, freeStorageSize) ? 'rebuild'
                     : '--  ';
      console.log(`  [yellow]${'━'.repeat(termWidth - 2)}[/]`);
      if (name.length > 64) name = `${name.substring(0, indexWidth)}~`;
      console.log(`   [red]${name.padEnd(indexWidth)}[/] ${formatUnit(storageSize).padStart(columnWidth)} ${(formatUnit(freeStorageSize) + ' |' + (formatPct(freeStorageSize, storageSize)).padStart(6)).padStart(columnWidth + 8)} ${''.toString().padStart(columnWidth)} [cyan]${compaction.padStart(columnWidth - 2)}[/]`);

      return;
   }

   function printDbHeader({ name } = {}) {
      /*
       *  Print DB table header
       */
      console.log('');
      console.log(`[yellow]${'═'.repeat(termWidth)}[/]`);
      console.log(`[bold][green]${`Database:[/] [cyan]${name}`.padEnd(rowHeader + 9)}[/] [bold][green]${'Data size'.padStart(columnWidth)} ${'Compression'.padStart(columnWidth + 1)} ${'Size on disk'.padStart(columnWidth)} ${'Free blocks | reuse'.padStart(columnWidth + 8)} ${'Object count'.padStart(columnWidth)}${'Compaction'.padStart(columnWidth - 1)}[/]`);

      return;
   }

   function printDb({
         shards, dataSize, compression, storageSize, freeStorageSize, objects, namespaces, nindexes, totalIndexSize, totalIndexBytesReusable
      } = {}) {
      /*
       *  Print DB level rollup stats
       */
      const dbCompaction = compactionHelper('collection', storageSize, freeStorageSize) ? 'compact' : '--  ';
      const dbIdxCompaction = compactionHelper('index', totalIndexSize, totalIndexBytesReusable) ? 'rebuild' : '--  ';
      console.log(`[yellow]${'━'.repeat(termWidth)}[/]`);
      if (shards.length > 0) {
         console.log(`[bold][green]${`Namespaces subtotal:[/]`.padEnd(rowHeader + 4)}${formatUnit(dataSize).padStart(columnWidth)} ${formatRatio(compression).padStart(columnWidth + 1)} ${formatUnit(storageSize).padStart(columnWidth)} ${(formatUnit(freeStorageSize).padStart(columnWidth) + ' |' + `${formatPct(freeStorageSize, storageSize)}`.padStart(6)).padStart(columnWidth + 8)} ${objects.toString().padStart(columnWidth)} [cyan]${dbCompaction.padStart(columnWidth - 2)}[/]`);
         namespaces = JSON.stringify(
            shards.map((shard, _i) => {
               return { [shard]: namespaces[_i] }
            }), null, 3
         // ).replace(/(?<![\[])(?:\n\s+)/g, ' '); // legacy shell doesn't support this
         ).replace(/(?:\n\s+)|(?:\n)/g, ' ');
         console.log(namespaces);
         console.log(`[bold][green]${`Indexes subtotal:[/]`.padEnd(rowHeader + 4)}${''.padStart(columnWidth)} ${''.padStart(columnWidth + 1)} ${formatUnit(totalIndexSize).padStart(columnWidth)} ${`${formatUnit(totalIndexBytesReusable).padStart(columnWidth)} |${`${formatPct(totalIndexBytesReusable, totalIndexSize)}`.padStart(6)}`.padStart(columnWidth + 8)} ${''.toString().padStart(columnWidth)} [cyan]${dbIdxCompaction.padStart(columnWidth - 2)}[/]`);
         nindexes = JSON.stringify(
            shards.map((shard, _i) => {
               return { [shard]: nindexes[_i] }
            }), null, 3
         // ).replace(/(?<![\[])(?:\n\s+)/g, ' '); // legacy shell doesn't support this
         ).replace(/(?:\n\s+)|(?:\n)/g, ' ');
         console.log(nindexes);
      } else {
         console.log(`[bold][green]${`Namespaces subtotal:[/] ${JSON.stringify(namespaces)}`.padEnd(rowHeader + 4)}${formatUnit(dataSize).padStart(columnWidth)} ${formatRatio(compression).padStart(columnWidth + 1)} ${formatUnit(storageSize).padStart(columnWidth)} ${(formatUnit(freeStorageSize).padStart(columnWidth) + ' |' + `${formatPct(freeStorageSize, storageSize)}`.padStart(6)).padStart(columnWidth + 8)} ${objects.toString().padStart(columnWidth)} [cyan]${dbCompaction.padStart(columnWidth - 2)}[/]`);
         console.log(`[bold][green]${`Indexes subtotal:[/]    ${JSON.stringify(nindexes)}`.padEnd(rowHeader + 4)}${''.padStart(columnWidth)} ${''.padStart(columnWidth + 1)} ${formatUnit(totalIndexSize).padStart(columnWidth)} ${`${formatUnit(totalIndexBytesReusable).padStart(columnWidth)} |${`${formatPct(totalIndexBytesReusable, totalIndexSize)}`.padStart(6)}`.padStart(columnWidth + 8)} ${''.toString().padStart(columnWidth)} [cyan]${dbIdxCompaction.padStart(columnWidth - 2)}[/]`);
      }
      console.log(`[yellow]${'═'.repeat(termWidth)}[/]`);

      return;
   }

   function printDbPath({
         dbPath, shards, proc, hostname, compression, dataSize, storageSize, freeStorageSize, objects, namespaces, nindexes, totalIndexSize, totalIndexBytesReusable
      } = {}) {
      /*
       *  Print total dbPath rollup stats
       */
      const dbPathCompaction = compactionHelper('dbPath', storageSize, freeStorageSize) ? 'resync' : '--  ';
      const dbPathIdxCompaction = compactionHelper('index', totalIndexSize, totalIndexBytesReusable) ? 'rebuild' : '--  ';
      console.log('');
      console.log(`[yellow]${'═'.repeat(termWidth)}[/]`);
      console.log(`[bold][green]${'dbPath totals'.padEnd(rowHeader)} ${'Data size'.padStart(columnWidth)} ${'Compression'.padStart(columnWidth + 1)} ${'Size on disk'.padStart(columnWidth)} ${'Free blocks | reuse'.padStart(columnWidth + 8)} ${'Object count'.padStart(columnWidth)}${'Compaction'.padStart(columnWidth - 1)}[/]`);
      console.log(`[yellow]${'━'.repeat(termWidth)}[/]`);
      if (shards.length > 0) {
         console.log(`[bold][green]${`All namespaces:[/]`.padEnd(rowHeader + 4)}${formatUnit(dataSize).padStart(columnWidth)} ${formatRatio(compression).padStart(columnWidth + 1)} ${formatUnit(storageSize).padStart(columnWidth)} ${(formatUnit(freeStorageSize) + ' |' + (formatPct(freeStorageSize, storageSize)).padStart(6)).padStart(columnWidth + 8)} ${objects.toString().padStart(columnWidth)} [cyan]${dbPathCompaction.padStart(columnWidth - 2)}[/]`);
         namespaces = JSON.stringify(
            shards.map((shard, _i) => {
               return { [shard]: namespaces[_i] }
            }), null, 3
         // ).replace(/(?<![\[])(?:\n\s+)/g, ' '); // legacy shell doesn't support this
         ).replace(/(?:\n\s+)|(?:\n)/g, ' ');
         console.log(namespaces);
         console.log(`[bold][green]${`All indexes:[/]`.padEnd(rowHeader + 4)}${''.padStart(columnWidth)} ${''.padStart(columnWidth + 1)} ${formatUnit(totalIndexSize).padStart(columnWidth)} ${(formatUnit(totalIndexBytesReusable) + ' |' + (formatPct(totalIndexBytesReusable, totalIndexSize)).padStart(6)).padStart(columnWidth + 8)} ${''.padStart(columnWidth)} [cyan]${dbPathIdxCompaction.padStart(columnWidth - 2)}[/]`);
         nindexes = JSON.stringify(
            shards.map((shard, _i) => {
               return { [shard]: nindexes[_i] }
            }), null, 3
         // ).replace(/(?<![\[])(?:\n\s+)/g, ' '); // legacy shell doesn't support this
         ).replace(/(?:\n\s+)|(?:\n)/g, ' ');
         console.log(nindexes);
      } else {
         console.log(`[bold][green]${`All namespaces:[/] ${JSON.stringify(namespaces)}`.padEnd(rowHeader + 4)}${formatUnit(dataSize).padStart(columnWidth)} ${formatRatio(compression).padStart(columnWidth + 1)} ${formatUnit(storageSize).padStart(columnWidth)} ${(formatUnit(freeStorageSize) + ' |' + (formatPct(freeStorageSize, storageSize)).padStart(6)).padStart(columnWidth + 8)} ${objects.toString().padStart(columnWidth)} [cyan]${dbPathCompaction.padStart(columnWidth - 2)}[/]`);
         console.log(`[bold][green]${`All indexes:[/]    ${JSON.stringify(nindexes)}`.padEnd(rowHeader + 4)}${''.padStart(columnWidth)} ${''.padStart(columnWidth + 1)} ${formatUnit(totalIndexSize).padStart(columnWidth)} ${(formatUnit(totalIndexBytesReusable) + ' |' + (formatPct(totalIndexBytesReusable, totalIndexSize)).padStart(6)).padStart(columnWidth + 8)} ${''.padStart(columnWidth)} [cyan]${dbPathIdxCompaction.padStart(columnWidth - 2)}[/]`);
      }
      console.log(`[yellow]${'═'.repeat(termWidth)}[/]`);
      console.log(`[bold][green]Host:[/] [cyan]${hostname}[/]   [bold][green]Type:[/] [cyan]${proc}[/]   [bold][green]Version:[/] [cyan]${db.version()}[/]   [bold][green]dbPath:[/] [cyan]${dbPath}[/]`);
      if (shards.length > 0) {
         console.log(`[bold][green]Shards:[/] ${JSON.stringify(shards)}`);
      }
      console.log(`[yellow]${'═'.repeat(termWidth)}[/]`);
      console.log('');

      return;
   }

   dbStats = await main();
   // return dbStats;
// })(db, options);
})();

// EOF
