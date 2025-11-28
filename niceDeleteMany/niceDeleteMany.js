(async() => {
   /*
    *  Name: "niceDeleteMany.js"
    *  Version: "0.2.6"
    *  Description: "nice concurrent/batch deleteMany() technique with admission control"
    *  Disclaimer: "https://raw.githubusercontent.com/tap1r/mongodb-scripts/master/DISCLAIMER.md"
    *  Authors: ["tap1r <luke.prochazka@gmail.com>"]
    *
    *  Notes:
    *  - Curation relies on a semi-blocking operator for bucket estimations
    *  - Good for matching up to 2,147,483,647,000 documents
    *
    *  TODOs:
    *  - re-add naïve timers for mongos/sharding support
    *  - add execution profiler/timers
    *  - add serverStatus() caching decorator
    *    - calculate smoothed decay/moving average metrics
    *    - debouce serverStatus() requests to fixed intervals
    *  - add progress counters with estimated time remaining
    *  - add congestion meter for admission control
    *  - add more granular/progressive admission control based on dirtyFill
    *  - add repl-lag metric for admission control
    *  - fix secondary reads for curation
    *  - add backoff expiry timer
    *  - add better sharding support
    *  - revise lowPriorityAdmissionBypassThreshold for backward compatibility
    *  - improve support for Atlas Flex tiers
    *  - build-in IXSCAN check to support the supplied filter
    */

   // Syntax: mongosh [connection options] [--quiet] [--eval 'let dbName = "", collName = "", filter = {}, hint = {}, collation = {}, safeguard = <bool>;'] [-f|--file] niceDeleteMany.js

   /*
    *  dbName: <string>      // (required) database name
    *  collName: <string>    // (required) collection name
    *  filter: <document>    // (optional) query filter
    *  hint: <document>      // (optional) query hint
    *  collation: <document> // (optional) query collation
    *  safeguard: <bool>     // (optional) simulates deletes only (via aborted transactions), set false to remove safeguard
    */

   // Example: mongosh --host "replset/localhost" --eval 'let dbName = "database", collName = "collection", filter = { "qty": { "$lte": 100 } }, safeguard = true;' niceDeleteMany.js

   /*
    *  Start user defined options defaults
    */

   typeof dbName !== 'string' && (dbName = '');
   typeof collName !== 'string' && (collName = '');
   typeof filter !== 'object' && (filter = {});
   typeof hint !== 'object' && (hint = {});
   typeof collation !== 'object' && (collation = {});
   typeof safeguard !== 'boolean' && (safeguard = true);

   /*
    *  End user defined options
    */

   const __script = { "name": "niceDeleteMany.js", "version": "0.2.6" };
   let banner = `#### Running script ${__script.name} v${__script.version} on shell v${version()}`;
   let vitals = {};

   async function* getIds(filter = {}, bucketSizeLimit = 100, sessionOpts = {}) {
      // _id curation (employs partial-blocking aggregation operators)
      const session = db.getMongo().startSession(sessionOpts);
      const namespace = session.getDatabase(dbName).getCollection(collName);
      // const buckets = Math.pow(2, 31) - 1; // max 32bit Int
      const aggOpts = {
         "allowDiskUse": true,
         "collation": collation,
         "cursor": { "batchSize": bucketSizeLimit * vitals.numCores }, // multiple of bucketSizeLimit * concurrency
         "hint": hint,
         "maxTimeMS": 0, // required to overide potential v8 defaultMaxTimeMS cluster settings
         "comment": "Bucketing IDs via niceDeleteMany.js",
         "let": { "bucketSizeLimit": bucketSizeLimit }
      };
      const pipeline = [
         { "$match": filter },
         /* v1 blocking mode with count estimations
            // { "$setWindowFields": {
            //    "sortBy": { "_id": 1 },
            //    "output": {
            //       "ordinal": { "$documentNumber": {} },
            //       "IDsTotal": { "$count": {} }
            // } } },
            // { "$bucketAuto": { // fixed height bucketing
            //    "groupBy": { "$ceil": { "$divide": ["$ordinal", "$$bucketSizeLimit"] } },
            //    "buckets": buckets,
            //    "output": {
            //       "IDs": { "$push": "$_id" },
            //       "bucketSize": { "$sum": 1 },
            //       "IDsTotal": { "$max": "$IDsTotal" }
            // } } },
            // { "$setWindowFields": {
            //    "sortBy": { "_id": 1 },
            //    "output": {
            //       "bucketId": { "$documentNumber": {} },
            //       "bucketsTotal": { "$count": {} },
            //       "IDsCumulative": {
            //          "$sum": "$bucketSize",
            //          "window": { "documents": ["unbounded", "current"] }
            // } } } },
         */
         /* v2 reduced non-blocking mode without count estimations
            // { "$setWindowFields": { // assign ordinal numbers incrementally
            //    "sortBy": { "_id": 1 },
            //    "output": { "ordinal": { "$documentNumber": {} } }
            // } },
            // { "$set": { // assign bucket IDs based on ordinal, avoiding full grouping
            //    "bucketId": { "$ceil": { "$divide": ["$ordinal", "$$bucketSizeLimit"] } }
            // } },
            // { "$group": { // group into buckets incrementally
            //    "_id": "$bucketId",
            //    "IDs": { "$push": "$_id" },
            //    "bucketSize": { "$sum": 1 }
            // } },
            // { "$setWindowFields": { // compute cumulative bucket sizes
            //    "sortBy": { "_id": 1 },
            //    "output": {
            //       "bucketId": { "$documentNumber": {} }, // renumber buckets sequentially
            //       "IDsCumulative": {
            //          "$sum": "$bucketSize",
            //          "window": { "documents": ["unbounded", "current"] }
            // } } } },
         */
         // v3 non-blocking mode
         { "$setWindowFields": { // assign ordinal numbers
            "sortBy": { [Object.keys(filter)[0]]: 1 },
            "output": { "ordinal": { "$documentNumber": {} } }
         } },
         { "$set": { // compute bucketId and running cumulative count
            "bucketId": { "$ceil": { "$divide": ["$ordinal", "$$bucketSizeLimit"] } },
            "cardinal": 1 // each document contributes 1 to its bucket
         } },
         { "$setWindowFields": { // compute cumulative sum in the bucket
            "partitionBy": "$bucketId",
            "sortBy": { [Object.keys(filter)[0]]: 1 },
            "output": {
               "IDsCumulative": {
                  "$sum": "$cardinal",
                  "window": { "documents": ["unbounded", "current"] }
               },
               "IDs": { "$push": "$_id" },
               "bucketSize": { "$sum": 1 }
            }
         } },
         { "$match": { // reduce to the last bucket of each group
            "$expr": {
               "$eq": ["$IDsCumulative", "$bucketSize"]
            }
         } },
         //
         { "$project": {
            "_id": 0,
            "bucketId": 1, // ordinal of current bucket
            // "bucketsTotal": 1, // total number of buckets
            // "bucketsRemaining": { "$subtract": ["$bucketsTotal", "$bucketId"] }, // number of buckets remaining
            "bucketSize": 1, // number of _ids in the current bucket
            "bucketSizeLimit": "$$bucketSizeLimit", // bucket size limit
            "IDsCumulative": 1, // cumulative total number of IDs
            // "IDsRemaining": { "$subtract": ["$IDsTotal", "$IDsCumulative"] }, // total number of IDs remaining
            "IDsTotal": 1, // total number of IDs
            "IDs": 1 // IDs in the current bucket
         } }
      ];
      // offload iterator to the server's cursor
      yield* namespace.aggregate(pipeline, aggOpts);
   }

   function countIds(filter = {}) {
      // cheaper count for validation purposes
      const session = db.getMongo().startSession({
         "causalConsistency": true,
         "readConcern": { "level": "local" },
         "mode": "primaryPreferred"
      });
      const namespace = session.getDatabase(dbName).getCollection(collName);
      const pipeline = [
            { "$match": filter },
            { "$group": {
               "_id": null,
               "IDsTotal": { "$count": {} }
            } },
            { "$project": {
               "_id": 0,
               "IDsTotal": 1 // total number of IDs
            } }
         ],
         aggOpts = {
            "allowDiskUse": true,
            "readOnce": true, // may or may not work in aggregation?
            // "readConcern": readConcern,
            "readConcern": "local",
            "collation": collation,
            "hint": hint,
            "comment": "Validating IDs via niceDeleteMany.js"
         };
      return namespace.aggregate(pipeline, aggOpts).toArray()[0]?.IDsTotal ?? 0;
   }

   async function deleteManyTask({ IDs, bucketId } = {}, sessionOpts = {}) {
      let sleepIntervalMS = await admissionControl();
      while (sleepIntervalMS == 'wait') {
         console.log('\t\t...batch', bucketId, 'is awaiting scheduling due to back pressure');
         sleep(Math.floor(500 + Math.random() * 500));
         sleepIntervalMS = await admissionControl();
      };
      console.log('\t\t...batch', bucketId, 'executing (buffering:', sleepIntervalMS, 'ms)');
      sleep(sleepIntervalMS);
      const session = db.getMongo().startSession(sessionOpts);
      const namespace = session.getDatabase(dbName).getCollection(collName);
      const txnOpts = {
         // "readConcern": { "level": "local" },
         // "writeConcern": {
         //    "w": "majority",
         //    "j": false
         // },
         "comment": `Simulating deleteMany(${JSON.stringify(filter)}) workload via niceDeleteMany.js`
      };
      const deleteManyFilter = { "_id": { "$in": IDs } };
      const deleteManyOpts = { "collation": collation };
      let deletedCount = 0;
      const deleteMany = async() => {
         return await namespace.deleteMany(deleteManyFilter, deleteManyOpts).deletedCount;
      }
      if (safeguard) {
         try {
            session.startTransaction(txnOpts);
            deletedCount = await deleteMany();
         } catch(error) {
            console.log('txn error:', error);
         } finally {
            session.abortTransaction();
         }
      } else {
         try {
            deletedCount = await deleteMany();
         } catch(error) {
            console.log(error);
         }
      }

      return [bucketId, deletedCount];
   }

   async function congestionMonitor() {
      /*
       *  congestionMonitor() function
       */
      async function serverStatus(serverStatusOptions = {}) {
         /*
          *  opt-in version of db.serverStatus()
          */
         const serverStatusOptionsDefaults = { // multiversion compatible
            "activeIndexBuilds": false,
            "asserts": false,
            "batchedDeletes": false,
            "bucketCatalog": false,
            "catalogStats": false,
            "changeStreamPreImages": false,
            "collectionCatalog": false,
            "connections": false,
            "defaultRWConcern": false,
            "electionMetrics": false,
            "encryptionAtRest": false,
            "extra_info": false,
            "featureCompatibilityVersion": false,
            "flowControl": false,
            "globalLock": false,
            "health": false,
            "hedgingMetrics": false,
            "indexBuilds": false,
            "indexBulkBuilder": false,
            "indexStats": false,
            "internalTransactions": false,
            "Instance Information": false,
            "latchAnalysis": false,
            "locks": false,
            "logicalSessionRecordCache": false,
            "mem": false,
            "metrics": false,
            "mirroredReads": false,
            "network": false,
            "opLatencies": false,
            "opReadConcernCounters": false,
            "opWorkingTime": false,
            "opWriteConcernCounters": false,
            "opcounters": false,
            "opcountersRepl": false,
            "oplogTruncation": false,
            "planCache": false,
            "queryAnalyzers": false,
            "querySettings": false,
            "queues": false,
            "readConcernCounters": false,
            "readPreferenceCounters": false,
            "repl": false,
            "scramCache": false,
            "security": false,
            "service": false,
            "sharding": false,
            "shardingStatistics": false,
            "shardedIndexConsistency": false,
            "shardSplits": false,
            "storageEngine": false,
            "tcmalloc": false,
            "tenantMigrations": false,
            "trafficRecording": false,
            "transactions": false,
            "transportSecurity": false,
            "twoPhaseCommitCoordinator": false,
            "watchdog": false,
            "wiredTiger": false,
            "writeBacksQueued": false
         };

         return await db.adminCommand({
            "serverStatus": true,
            ...{ ...serverStatusOptionsDefaults, ...serverStatusOptions }
         });
      }

      function hostInfo() {
         let hostInfo = {};
         try {
            hostInfo = db.hostInfo();
         } catch(error) {
            // console.debug(`\x1b[31m[WARN] insufficient rights to execute db.hostInfo()\n${error}\x1b[0m`);
         }

         return hostInfo;
      }

      function rsStatus() {
         let rsStatus = {};
         try {
            rsStatus = rs.status();
         } catch(error) {
            // console.debug(`\x1b[31m[WARN] insufficient rights to execute rs.status()\n${error}\x1b[0m`);
         }

         return rsStatus;
      }

      return {
         // WT eviction defaults (https://kb.corp.mongodb.com/article/000019073)
         // evictionThreadsMin,
         // evictionThreadsMax,
         // evictionCheckpointTarget,
         // evictionDirtyTarget,    // operate in a similar way to the overall targets but only apply to dirty data in cache
         // evictionDirtyTrigger,   // application threads will be throttled if the percentage of dirty data reaches the eviction_dirty_trigger
         // evictionTarget,         // the level at which WiredTiger attempts to keep the overall cache usage
         // evictionTrigger,        // the level at which application threads start to perform the eviction
         // evictionUpdatesTarget,  // eviction in worker threads when the cache contains at least this many bytes of updates
         // evictionUpdatesTrigger, // application threads to perform eviction when the cache contains at least this many bytes of updates
         "hostInfo": hostInfo(),
         "rsStatus": rsStatus(),
         "wiredTigerEngineRuntimeConfig": db.adminCommand({ "getParameter": 1, "wiredTigerEngineRuntimeConfig": 1 }).wiredTigerEngineRuntimeConfig,
         "storageEngineConcurrentReadTransactions": db.adminCommand({ "getParameter": 1, "wiredTigerConcurrentReadTransactions": 1 }).wiredTigerConcurrentReadTransactions,
         // db.adminCommand({ "getParameter": 1, "storageEngineConcurrentReadTransactions": 1 })
         "storageEngineConcurrentWriteTransactions": db.adminCommand({ "getParameter": 1, "wiredTigerConcurrentWriteTransactions": 1 }).wiredTigerConcurrentWriteTransactions,
         // "lowPriorityAdmissionBypassThreshold": db.adminCommand({ "getParameter": 1, "lowPriorityAdmissionBypassThreshold": 1 }).lowPriorityAdmissionBypassThreshold,
         // https://www.mongodb.com/docs/manual/reference/command/serverStatus/#mongodb-serverstatus-serverstatus.wiredTiger.concurrentTransactions
         "serverStatus": await serverStatus({ // minimal server status metrics to reduce server cost
            "activeIndexBuilds": true,
            "flowControl": true,
            "indexBuilds": true,
            "mem": true,
            "metrics": true,
            "queues": true,
            "storageEngine": true,
            "tenantMigrations": true,
            "tcmalloc": true, // 2 for more debugging
            "wiredTiger": true
         }),
         "slowms": db.getSiblingDB('admin').getProfilingStatus().slowms,
         wterc(regex) {
            // { "wiredTigerEngineRuntimeConfig": "eviction=(threads_min=8,threads_max=8),eviction_dirty_target=2,eviction_updates_trigger=8,checkpoint=(wait=60,log_size=2GB)" }
            return this.wiredTigerEngineRuntimeConfig.match(regex)?.[1] ?? null;
         },
         get evictionThreadsMin() {
            return +(this.wterc(/eviction=\(.*threads_min=(\d+).*\)/) ?? 4);
         },
         get evictionThreadsMax() {
            return +(this.wterc(/eviction=\(.*threads_max=(\d+).*\)/) ?? 4);
         },
         get evictionCheckpointTarget() {
            return +(this.wterc(/eviction_checkpoint_target=(\d+)/) ?? 1);
         },
         get evictionDirtyTarget() {
            return +(this.wterc(/eviction_dirty_target=(\d+)/) ?? 5);
         },
         get evictionDirtyTrigger() {
            return +(this.wterc(/eviction_dirty_trigger=(\d+)/) ?? 20);
         },
         get evictionTarget() {
            return +(this.wterc(/eviction_target=(\d+)/) ?? 80);
         },
         get evictionTrigger() {
            return +(this.wterc(/eviction_trigger=(\d+)/) ?? 95);
         },
         get evictionUpdatesTarget() {
            return +(this.wterc(/eviction_updates_target=(\d+)/) ?? 2.5);
         },
         get evictionUpdatesTrigger() {
            return +(this.wterc(/eviction_updates_trigger=(\d+)/) ?? 10);
         },
         get checkpointIntervalMS() { // checkpoint=(wait=60
            return 1000 * (this.wterc(/checkpoint=\(.*wait=(\d+).*\)/) ?? 60);
         },
         get updatesDirtyBytes() {
            return this.serverStatus.wiredTiger.cache['bytes allocated for updates'];
         },
         get dirtyBytes() {
            return +this.serverStatus.wiredTiger.cache['tracked dirty bytes in the cache'];
         },
         get cacheSizeBytes() {
            return +this.serverStatus.wiredTiger.cache['maximum bytes configured'];
         },
         get cachedBytes() {
            return this.serverStatus.wiredTiger.cache['bytes currently in the cache'];
         },
         get cacheUtil() {
            return Number.parseFloat(((this.cachedBytes / this.cacheSizeBytes) * 100).toFixed(2));
         },
         get cacheStatus() {
            return (this.cacheUtil < this.evictionTarget) ? 'low'
                 : (this.cacheUtil > this.evictionTrigger) ? 'high'
                 : 'medium';
         },
         get dirtyUtil() {
            return Number.parseFloat(((this.dirtyBytes / this.cacheSizeBytes) * 100).toFixed(2));
         },
         get dirtyStatus() {
            return (this.dirtyUtil < this.evictionDirtyTarget) ? 'low'
                 : (this.dirtyUtil > this.evictionDirtyTrigger) ? 'high'
                 : 'medium';
         },
         get dirtyUpdatesUtil() {
            return Number.parseFloat(((this.updatesDirtyBytes / this.cacheSizeBytes) * 100).toFixed(2));
         },
         get dirtyUpdatesStatus() {
            return (this.dirtyUpdatesUtil < this.evictionUpdatesTarget) ? 'low'
                 : (this.dirtyUpdatesUtil > this.evictionUpdatesTrigger) ? 'high'
                 : 'medium';
         },
         get cacheEvictions() {
            return (this.cacheUtil > this.evictionTrigger);
         },
         get dirtyCacheEvictions() {
            return (this.dirtyUtil > this.evictionDirtyTrigger);
         },
         get dirtyUpdatesCacheEvictions() {
            return (this.dirtyUpdatesUtil > this.evictionUpdatesTrigger);
         },
         get evictionsTriggered() {
            return (this.cacheEvictions || this.dirtyCacheEvictions || this.dirtyUpdatesCacheEvictions);
         },
         get cacheHitRatio() {
            const hitBytes = this.serverStatus.wiredTiger.cache['pages requested from the cache'];
            const missBytes = this.serverStatus.wiredTiger.cache['pages read into cache'];
            return Number.parseFloat((100 * (hitBytes - missBytes) / hitBytes).toFixed(2));
         },
         get cacheHitStatus() {
            return (this.cacheHitRatio < 20) ? 'high'
                 : (this.cacheHitRatio > 75) ? 'low'
                 : 'medium';
         },
         get cacheMissRatio() {
            const hitBytes = this.serverStatus.wiredTiger.cache['pages requested from the cache'];
            const missBytes = this.serverStatus.wiredTiger.cache['pages read into cache'];
            return Number.parseFloat((100 * (1 - (hitBytes - missBytes) / hitBytes)).toFixed(2));
         },
         get cacheMissStatus() {
            return (this.cacheMissRatio < 20) ? 'low'
                 : (this.cacheMissRatio > 75) ? 'high'
                 : 'medium';
         },
         get memSizeBytes() {
            // return (this?.hostInfo?.system?.memSizeMB ?? 1024) * 1024 * 1024;
            return (this?.hostInfo?.system?.memLimitMB ?? 1024) * 1024 * 1024;
         },
         get numCores() {
            // else max 4 is probably a good default aligning with concurrency limits
            return this?.hostInfo?.system?.numCores ?? 4;
         },
         get memResidentBytes() {
            return (this.serverStatus.mem?.resident ?? 0) * 1024 * 1024;
         },
         get currentAllocatedBytes() {
            return +(this.serverStatus?.tcmalloc?.generic?.current_allocated_bytes ?? 0);
         },
         get heapSize() {
            return +(this.serverStatus?.tcmalloc?.generic?.heap_size ?? (this.memSizeBytes / 64));
         },
         get heapUtil() {
            return Number.parseFloat((100 * (this.currentAllocatedBytes / this.heapSize)).toFixed(2));
         },
         get pageheapFreeBytes() {
            // assume zero fragmentation if we cannot measure pageheap_free_bytes
            return +(this.serverStatus?.tcmalloc?.tcmalloc?.pageheap_free_bytes ?? 0);
         },
         get totalFreeBytes() {
            return +(this.serverStatus?.tcmalloc?.tcmalloc?.total_free_bytes ?? 0);
         },
         get memoryFragmentationRatio() {
            return Number.parseFloat(((this.pageheapFreeBytes / this.memSizeBytes) * 100).toFixed(2));
         },
         get memoryFragmentationStatus() {
            // mimicing the (bad) t2 derived metric for now
            return (this.memoryFragmentationRatio < 10) ? 'low'  // 25 is more realistic
                 : (this.memoryFragmentationRatio > 30) ? 'high' // 50 is more realistic
                 : 'medium';
         },
         get backupCursorOpen() {
            return this.serverStatus.storageEngine.backupCursorOpen;
         },
         // WT tickets available
         // v6.0 (and older)
         // {
         //    write: { out: 0, available: 128, totalTickets: 128 },
         //    read: { out: 0, available: 128, totalTickets: 128 }
         //  }
         // v7.0+
         //    write: {
         //      out: 0,
         //      available: 13,
         //      totalTickets: 13,
         //      queueLength: Long('0'),
         //      processing: Long('0')
         //    },
         //    read: {
         //      out: 0,
         //      available: 13,
         //      totalTickets: 13,
         //      queueLength: Long('0'),
         //      processing: Long('0')
         //    }
         // v8.0 see db.serverStats().queues.execution
         get wtReadTicketsUtil() {
            const { out, totalTickets } = this.serverStatus.wiredTiger?.concurrentTransactions?.read ?? this.serverStatus?.queues?.execution?.read;
            return Number.parseFloat(((out / totalTickets) * 100).toFixed(2));
         },
         get wtReadTicketsAvail() {
            const { available, totalTickets } = this.serverStatus.wiredTiger?.concurrentTransactions?.read ?? this.serverStatus?.queues?.execution?.read;
            return Number.parseFloat(((available / totalTickets) * 100).toFixed(2));
         },
         get wtWriteTicketsUtil() {
            const { out, totalTickets } = this.serverStatus.wiredTiger?.concurrentTransactions?.write ?? this.serverStatus?.queues?.execution?.write;
            return Number.parseFloat(((out / totalTickets) * 100).toFixed(2));
         },
         get wtWriteTicketsAvail() {
            const { available, totalTickets } = this.serverStatus.wiredTiger?.concurrentTransactions?.write ?? this.serverStatus?.queues?.execution?.write;
            return Number.parseFloat(((available / totalTickets) * 100).toFixed(2));
         },
         get wtReadTicketsStatus() {
            return (this.wtReadTicketsUtil < 20) ? 'low'
                 : (this.wtReadTicketsUtil > 75) ? 'high'
                 : 'medium';
         },
         get wtWriteTicketsStatus() {
            return (this.wtWriteTicketsUtil < 20) ? 'low'
                 : (this.wtWriteTicketsUtil > 75) ? 'high'
                 : 'medium';
         },
         get activeShardMigrations() {
            const { currentMigrationsDonating, currentMigrationsReceiving } = this.serverStatus.tenantMigrations;
            return (currentMigrationsDonating > 0 || currentMigrationsReceiving > 0);
         },
         get activeFlowControl() {
            return (this.serverStatus.flowControl.isLagged === true && this.serverStatus.flowControl.enabled === true);
         },
         get activeIndexBuilds() {
            return (this.serverStatus?.indexBuilds?.total ?? 0) > (this.serverStatus?.indexBuilds?.phases?.commit ?? 0) || (this.serverStatus?.activeIndexBuilds?.total ?? 0) > 0;
         },
         get activeCheckpoint() {
            return !!(this.serverStatus.wiredTiger.transaction?.['transaction checkpoint currently running'] || this.serverStatus.wiredTiger?.checkpoint?.['progress state']);
         },
         get slowRecentCheckpoint() {
            return (this.serverStatus.wiredTiger.transaction['transaction checkpoint most recent time (msecs)'] > 60000);
         },
         get checkpointRuntimeRatio() {
            return Number.parseFloat((((this.serverStatus.wiredTiger.transaction?.['transaction checkpoint most recent time (msecs)'] ?? this.serverStatus.wiredTiger.checkpoint?.['most recent time (msecs)']) / this.checkpointIntervalMS) * 100).toFixed(2));
         },
         get checkpointStatus() {
            return (this.checkpointRuntimeRatio < 50) ? 'low'
                 : (this.checkpointRuntimeRatio > 100) ? 'high'
                 : 'medium';
         },
         get activeReplLag() { // calculate the highest repl-lag from healthy members
            const opTimers = this.rsStatus.members.map(({
               stateStr,
               health,
               optimeDate
            } = {}) => {
               return {
                  "stateStr": stateStr,
                  "health": health,
                  "optimeDate": optimeDate
               };
            }).filter(({ health, stateStr }) => {
               return (health && (stateStr === 'PRIMARY' || stateStr === 'SECONDARY'));
            }).map(({ optimeDate }) => optimeDate);
            return +((Math.max(...opTimers) - Math.min(...opTimers)) / 1000).toFixed(0);
         },
         get replLagStatus() {
            return (this.activeReplLag < this.heartbeatIntervalMillis / 1000) ? 'low'
                 : (this.activeReplLag > 90) ? 'high' // maxStalenessSeconds
                 : 'medium';
         },
         get replLagScale() {
            return 30;
         },
         get heartbeatIntervalMillis() {
            return this.rsStatus.heartbeatIntervalMillis;
         }
      };
   }

   async function admissionControl() {
      /*
       *  dynamic admission controller
       *  - threads should not compete under these contended conditions
       *  - see also https://jira.mongodb.org/browse/SPM-1123
       */

      const {
         cacheStatus,
         dirtyStatus,
         dirtyUpdatesStatus,
         // wtReadTicketsStatus,
         wtWriteTicketsStatus,
         checkpointStatus
      } = await congestionMonitor();

      // heuristics based on write workload pattern (add mongos detection here)
      return (cacheStatus == 'high' || dirtyStatus == 'high' || dirtyUpdatesStatus == 'high') ? 'wait' // WT app threads evicting, we should not contribute to excess cache pressure
           : (dirtyStatus == 'medium' || dirtyUpdatesStatus == 'medium') ? Math.floor(20 + Math.random() * 80) // moderate write cache pressure, we can pause slightly
           : (wtWriteTicketsStatus == 'high' && checkpointStatus == 'high') ? Math.floor(100 + Math.random() * 100) // tickets highly contended, we should mitigate storage pressure
           : 0; // no cache pressure, we can open up the throttle
   }

   async function* asyncThreadPool(method = () => {}, threads = [], poolSize = 1, sessionOpts = {}) {
      const executing = new Set();
      async function consume() {
         const [threadPromise, thread] = await Promise.race(executing);
         executing.delete(threadPromise);
         return thread;
      }

      for await (const thread of threads) {
         /*
          *  Wrap method() in an async fn to ensure we get a promise.
          *  Then expose such promise, so it's possible to later reference
          *  and remove it from the executing pool.
          */
         // let msg = `\n\n\tScheduling batch ${thread.bucketId} with ${thread.bucketsRemaining} buckets queued remaining:\n`;
         let msg = `\n\n\tScheduling batch# ${thread.bucketId}:\n`;
         msg = banner + msg;
         console.clear();
         console.log(msg);
         const threadPromise = (async() => method(thread, sessionOpts))().then(
            thread => [threadPromise, thread]
         );
         executing.add(threadPromise);
         if (executing.size >= poolSize) yield await consume();
      }

      while (executing.size) yield await consume();
   }

   async function main() {
      vitals = await congestionMonitor();
      const { numCores } = vitals;
      const concurrency = (numCores > 4) ? numCores : 4; // see https://www.mongodb.com/docs/manual/reference/parameters/#mongodb-parameter-param.wiredTigerConcurrentWriteTransactions
      const bucketSizeLimit = 100; // aligns with SPM-2227
      const readConcern = { "level": "local" }, writeConcern = { "w": "majority" }; // support monotonic writes
      const readPreference = {
         // "mode": "nearest", // offload the bucket generation to a less busy node
         "mode": "secondaryPreferred", // offload the bucket generation to a different node
         "tags": [ // Atlas friendly defaults
            { "nodeType": "READ_ONLY", "diskState": "READY" },
            { "nodeType": "ANALYTICS", "diskState": "READY" },
            { "workloadType": "OPERATIONAL", "diskState": "READY" },
            { "diskState": "READY" },
            {}
         ]
      };
      const sessionOpts = {
         "causalConsistency": true,
         "readConcern": readConcern,
         "readPreference": readPreference,
         "retryWrites": true,
         "writeConcern": writeConcern
      };
      banner = `\n\x1b[33m${banner}\x1b[0m`;
      banner += `\n\nCurating '\x1b[32m_id\x1b[0m' deletion list from namespace:` +
                `\n\n\t\x1b[32m${dbName}.${collName}\x1b[0m` +
                `\n\nwith filter:` +
                `\n\n\t\x1b[32m${JSON.stringify(filter)}\x1b[0m` +
                `\n\n...please wait\n`;
      if (safeguard) {
         banner += '\n\x1b[31mWarning:\x1b[0m \x1b[32mSafeguard is enabled, simulating deletes only (via transaction rollbacks)\n\x1b[0m';
      }
      console.clear();
      console.log(banner);
      const deletionList = getIds(filter, bucketSizeLimit, sessionOpts);
      const { 'value': initialBatch, 'done': initialEmptyBatch } = await deletionList.next();
      if (initialEmptyBatch === true) {
         console.log('\tNo matching documents found to match the filter, double-check the namespace and filter');
      } else {
         // initial batch
         // let msg = `\nForking ${initialBatch.bucketsTotal} batches of ${initialBatch.bucketSizeLimit} documents with concurrency execution of ${concurrency} to delete ${initialBatch.IDsTotal} documents`;
         let msg = `\nForking ${concurrency} threads of ${initialBatch.bucketSizeLimit} batched documents`;
         banner += msg;
         console.log(msg);
         for await (const [bucketId, deletedCount] of asyncThreadPool(deleteManyTask, [initialBatch], concurrency, sessionOpts)) {
            console.log('\t\t...batch#', bucketId, 'deleted', deletedCount, 'documents');
         }
         // remaining batches
         for await (const [bucketId, deletedCount] of asyncThreadPool(deleteManyTask, deletionList, concurrency, sessionOpts)) {
            console.log('\t\t...batch#', bucketId, 'deleted', deletedCount, 'documents');
         }
      }
      console.log(`\nValidating deletion results ...please wait\n`);
      const finalCount = countIds(filter);
      if (safeguard) {
         console.log('Simulation safeguard is enabled, no deletions were actually performed:\n');
      }
      // console.log('\tInitial document count matching filter:', (initialEmptyBatch === true) ? 0 : initialBatch.IDsTotal);
      console.log('\tResidual document count matching filter:', finalCount);
      console.log('\nDone!');
   }

   await main().finally(console.log);
})();

// EOF
