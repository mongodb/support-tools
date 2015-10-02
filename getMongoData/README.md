MongoDB Support Tools
=====================

getMongoData.js
---------------

### Description

`getMongoData.js` is a utility to gather MongoDB configuration and schema information.
See [getMongoData.log](sample/getMongoData.log) for sample output.


### Usage

To execute on a locally running `mongod` on default port (27017) without authentication, run:

    mongo --quiet --norc getMongoData.js > getMongoData.log

To execute on a remote `mongod` or `mongos` with authentication, run:

    mongo HOST:PORT/admin -u ADMIN_USER -p ADMIN_PASSWORD --quiet --norc getMongoData.js > getMongoData.log

If `ADMIN_PASSWORD` is omitted, the shell will prompt for the password.

To have the output be in a JSON format, modify the above commands to include the following eval argument,
as demonstrated for the local execution:

    mongo --quiet --norc --eval "var _printJSON=true" getMongoData.js > getMongoData.json

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
