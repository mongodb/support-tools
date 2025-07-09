/*
 *  Name: "latency.js"
 *  Version: "0.4.6"
 *  Description: "Driver and network latency telemetry"
 *  Authors: ["Luke Prochazka <luke.prochazka@mongodb.com>"]
 */

// Usage: [mongo|mongosh] [connection options] --quiet [-f|--file] latency.js

// Example: mongosh --host "replset/localhost" --quiet latency.js

(() => {
   /*
    *  main
    */
   const __script = { "name": "latency.js", "version": "0.4.6" };
   if (typeof console === 'undefined') {
      /*
       *  legacy mongo detected
       */
      var console = {
         log: print,
         clear: () => _runMongoProgram('clear'),
         error: arg => printjson(arg, '', true, 64),
         debug: arg => printjson(arg, '', true, 64),
         dir: arg => printjson(arg, '', true, 64)
      };
      var EJSON = { parse: JSON.parse };
   }
   console.log(`\n\x1b[33m#### Running script ${__script.name} v${__script.version} on shell v${this.version()}\x1b[0m`);

   const spacing = 1;
   const filter = `Synthetic slow operation at ${Date.now()}`;
   const options = {
      "comment": filter,
      "cursor": { "batchSize": 1 },
      "readConcern": { "level": "local" }
   };
   let t0, t1, t2, t3;
   try {
      var { slowms = 100 } = db.getSiblingDB('admin').getProfilingStatus();
   } catch(error) {
      var slowms = 200;
      // console.log('\x1b[31m[WARN] failed to aquire the slowms threshold:\x1b[0m', error);
      console.log(`\x1b[31m[WARN] defaulting slowms to ${slowms}ms\x1b[0m`);
   }
   const pipeline = [
      { "$currentOp": {} },
      { "$limit": 1 },
      { "$project": {
         "_id": 0,
         "slowms": {
            // deprecated operator in v8, likely to be replaced with a future $sleep operator
            "$function": { // unsupported on Flex tier
               "body": `function(ms) { sleep(ms) }`,
               "args": [slowms],
               "lang": "js"
      } } } }
   ];

   const {
      'me': hostname,
      primary,
      'tags': {
         workloadType = '-',
         availabilityZone = '-',
         diskState = '-',
         nodeType = '-',
         provider = '-',
         region = '-'
      } = {} } = db.hello();

   const role = (primary == hostname) ? 'Primary' : 'Secondary';
   try {
      var { 'process': procType = 'unknown' } = db.serverStatus(
         { // multiversion compatible
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
         }
      );
   } catch(error) {
      var procType = 'unknown';
      console.log('\x1b[31m[WARN] failed to aquire the process type:\x1b[0m', error);
   }

   try {
      t0 = Date.now();
      // add server check for security.javascriptEnabled startup option
      db.getSiblingDB('admin').aggregate(pipeline, options).toArray();
   } catch(error) {
      t0 = Date.now();
      console.log('Synthetic slow query failed');
      throw error;
   } finally {
      t1 = Date.now();
   }

   const [{ 'attr': { durationMillis = 0 } = {} } = {}] = db.adminCommand(
      { "getLog": "global" }
   ).log.map(
      EJSON.parse
   ).filter(
      ({ 'attr': { 'command': { comment = '' } = {} } = {} } = {}) => {
         return comment == filter;
      }
   );

   try {
      t2 = Date.now();
      var { 'ok': ping = 0 } = db.adminCommand({ "ping": 1 });
   } catch(error) {
      t2 = Date.now();
      console.error('SDAM ping failed');
      throw error;
   } finally {
      t3 = Date.now();
      if (!ping) throw new Error();
   }

   const timestamp = new Date().toISOString();
   const totalTime = t1 - t0;
   const rtt = t3 - t2;
   const hostLength = 'Host:'.length + spacing + hostname.length;
   const timeLength = 'Timestamp:'.length + spacing + timestamp.length;
   const tableWidth = Math.max(hostLength, timeLength);
   const serverTime = durationMillis - slowms;
   const driverTime = totalTime - durationMillis - rtt;
   const report = `\n` +
      `\x1b[1mInternal metrics\x1b[0m\n` +
      `\x1b[33m${'━'.repeat(tableWidth)}\x1b[0m\n` +
      `\x1b[32m${'Host:'}\x1b[0m${hostname.padStart(tableWidth - 'Host:'.length)}\n` +
      `\x1b[32m${'Process:'}\x1b[0m${procType.padStart(tableWidth - 'Process:'.length)}\n` +
      `\x1b[32m${'Role:'}\x1b[0m${role.padStart(tableWidth - 'Role:'.length)}\n` +
      `\x1b[32m${'Cloud provider:'}\x1b[0m${provider.padStart(tableWidth - 'Cloud provider:'.length)}\n` +
      `\x1b[32m${'Cloud region:'}\x1b[0m${region.padStart(tableWidth - 'Cloud region:'.length)}\n` +
      `\x1b[32m${'Availability zone:'}\x1b[0m${availabilityZone.padStart(tableWidth - 'Availability zone:'.length)}\n` +
      `\x1b[32m${'Disk state:'}\x1b[0m${diskState.padStart(tableWidth - 'Disk state:'.length)}\n` +
      `\x1b[32m${'Workload type:'}\x1b[0m${workloadType.padStart(tableWidth - 'Workload type:'.length)}\n` +
      `\x1b[32m${'Node type:'}\x1b[0m${nodeType.padStart(tableWidth - 'Node type:'.length)}\n` +
      `\x1b[32m${'Timestamp:'}\x1b[0m${timestamp.padStart(tableWidth - 'Timestamp:'.length)}\n` +
      `\x1b[32m${'Delay factor (slowms):'}\x1b[0m${`${slowms} ms`.padStart(tableWidth - 'Delay factor (slowms):'.length)}\n` +
      `\x1b[32m${'Total measurement time:'}\x1b[0m${`${totalTime} ms`.padStart(tableWidth - 'Total measurement time:'.length)}\n` +
      `\x1b[33m${'═'.repeat(tableWidth)}\x1b[0m\n` +
      `\n` +
      `\x1b[1mLatency breakdown\x1b[0m\n` +
      `\x1b[33m${'━'.repeat(tableWidth)}\x1b[0m\n` +
      `\x1b[32m${'Server execution time:'}\x1b[0m${`${serverTime} ms`.padStart(tableWidth - 'Server execution time:'.length)}\n` +
      `\x1b[32m${'Network latency (RTT):'}\x1b[0m${`${rtt} ms`.padStart(tableWidth - 'Network latency (RTT):'.length)}\n` +
      `\x1b[32m${'Driver execution time:'}\x1b[0m${`${driverTime} ms`.padStart(tableWidth - 'Driver execution time:'.length)}\n` +
      `\x1b[33m${'═'.repeat(tableWidth)}\x1b[0m\n`;
   console.log(report);
})();

// EOF
