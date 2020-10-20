MongoDB Support Tools
=====================

orphanage.js
------------

## This script is provided for historical reference only

MongoDB 2.6 adds the cleanupOrphaned command which should always be preferred to this script. Deleting orphans with this script should only be used on MongoDB versions prior to 2.6 Additionally in MongoDB 4.4, orphans are less likely to be created due to improved resilience on the deletion process.

### Description

orphanage.js is a utility to find and remove orphaned documents.

### Usage

 - sh.stopBalancer()               -- Stop the balancer
 - Orphans.setOutputNS('test.orphan_output') -- Save badChunks to a collection and suppress output
 - Orphans.preFlight()             -- Make connections ahead of time to prevent screen clutter during find/findAll type commands
 - Orphans.find('database.collection') -- Find orphans in a given namespace
 - Orphans.findAll()               -- Find orphans in all namespaces
 - Orphans.remove()                -- Removes the next chunk

Run orphanage.js without arguments to see the full help text.

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
