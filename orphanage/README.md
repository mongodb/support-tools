MongoDB Support Tools
=====================

orphanage.js
------------

### Description

orphanage.js is a utility to find and remove orphaned documents.

### Usage

 - sh.stopBalancer()               -- Stop the balancer
 - Orphans.setOutputNS('test.orphan_output')  -- Enabled summary view and saves badDocs to given location
 - Orphans.preFlight() --  Does all the connecitons output ahead of time, as to not  clutter  find/findAll type commands.
 - Orphans.find('db.collection')   -- Find orphans in a given namespace
 - Orphans.findAll()               -- Find orphans in all namespaces
 - Orphans.remove()                -- Removes the next chunk

Run orphanage.js without arguments to see the full help text.

### License


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
