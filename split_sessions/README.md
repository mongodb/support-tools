MongoDB Support Tools
=====================

split_sessions.js
-----------------

### Description

_indexStats.js_ is a script to be executed in Sharded Clusters to split the _config.system.sessions_ collection in as many chunks as Shards present in the Cluster at the moment of execution.

To successfully execute the script, the following role must be granted to the user executing it:
 - db.createRole({role:"split-config-system-sessions","privileges":[{"resource":{"db":"config","collection":"system.sessions"},"actions":["splitchunk","splitVector","collStats"]},{"resource":{"db":"config","collection":"collections"},"actions":["update"]},{"resource":{"db":"config","collection":"system.sessions"},"actions":["movechunk"]}],roles:[]})

### Usage

Run _split_sessions.js_ via Mongo Shell connectiong to a _mongos_.
 - mongo --host <mongos_host> --port <mongos_port> -u session_split_usr /path/to/split_sessions.js 
 

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