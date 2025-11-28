MongoDB Support Tools
=====================

## niceDeleteMany.js

**niceDeleteMany.js** is a script designed for use with the mongosh shell. It provides a method to delete a large number of documents while monitoring server performance to throttle the deletes and reduce impact on a database that is handling production workloads.

Metrics that are monitored to gauge cluster performance includes things such as how many [WiredTiger tickets](https://support.mongodb.com/article/000019039) are available, if [Flow Control](https://www.mongodb.com/docs/manual/replication/#replication-lag-and-flow-control) is active, current [Replication lag](https://www.mongodb.com/docs/manual/reference/glossary/#std-term-replication-lag), etc.

### Syntax
   
   ```
   mongosh [connection options] [--quiet] [--eval 'let dbName = "", collName = "", filter = {}, hint = {}, collation = {}, safeguard = <bool>;'] [-f|--file] niceDeleteMany.js

   dbName: <string>      // (required) database name
   collName: <string>    // (required) collection name
   filter: <document>    // (optional) query filter
   hint: <document>      // (optional) query hint
   collation: <document> // (optional) query collation
   safeguard: <bool>     // (optional) simulates deletes only (via aborted transactions), set false to remove safeguard
   ```

### Example
   ```
   mongosh --host "replset/localhost" --eval 'let dbName = "database", collName = "collection", filter = { "qty": { "$lte": 100 } }, safeguard = true;' niceDeleteMany.js
   ```

#### Notes
 - Curation relies on a semi-blocking operator for bucket estimations
 - Good for matching up to 2,147,483,647,000 documents

#### TODOs
  - re-add naïve timers for mongos/sharding support
  - add execution profiler/timers
  - add serverStatus() caching decorator
  - calculate smoothed decay/moving average metrics
  - debouce serverStatus() requests to fixed intervals
  - add progress counters with estimated time remaining
  - add congestion meter for admission control
  - add more granular/progressive admission control based on dirtyFill
  - add repl-lag metric for admission control
  - fix secondary reads for curation
  - add backoff expiry timer
  - add better sharding support
  - revise lowPriorityAdmissionBypassThreshold for backward compatibility
  - improve support for Atlas Flex tiers
  - build-in IXSCAN check to support the supplied filter

### License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)


DISCLAIMER
----------
Please note: all tools/ scripts in this repo are released for use "AS IS" **without any warranties of any kind**,
including, but not limited to their installation, use, or performance.  We disclaim any and all warranties, either 
express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness 
for a particular purpose.  We do not warrant that the technology will meet your requirements, that the operation 
thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is **at your own risk**.  There is no guarantee that they have been through 
thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with 
their use.

You are responsible for reviewing and testing any scripts you run *thoroughly* before use in any non-testing 
environment.

Thanks,  
The MongoDB Support Team