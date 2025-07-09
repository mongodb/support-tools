# MongoDB latency telemetry

**latency.js** is a script designed for use with the mongosh shell. It provides a granular breakdown of MongoDB operation latencies — including network, server, and driver latencies — to help you diagnose and optimize your MongoDB deployment.

### Features

 * Measures and reports:
   * Network latency
   * Server latency (query execution time)
   * Driver latency
* Suitable for local and remote MongoDB deployments

### Usage

1. Download [latency.js](latency.js) from this repository.
1. Open a terminal and start [mongosh](https://www.mongodb.com/docs/mongodb-shell/) with the following command line:

   `mongosh [connection options] --quiet [-f|--file] latency.js`

### Caveats

This script makes use of the [$function](https://www.mongodb.com/docs/manual/reference/operator/aggregation/function/) operator, which is unsupported on some Atlas tiers.

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