MongoDB Support Tools
=====================

indexStats.js
------------

### Description

indexStats.js is a utility that will collect index usage statistics for a MongoDB collection cross-cluster and provide aggregated results. It can be used to help determine whether there are unused/little used indexes that can be dropped.

Warning: The statistics provided by this utility SHOULD NOT be the sole means used for making a decision to drop an index. Please make sure to validate any changes in a non-production environment and make sure that the sample taken covers all use cases on the given collection.

### Usage

Run indexStats.js via mongo shell and follow directions given.
 - mongo --shell indexStats.js 
 

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
