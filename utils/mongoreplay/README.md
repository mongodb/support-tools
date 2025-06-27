# mongoreplay
Starting in MongoDB 4.4, `mongoreplay` was removed from MongoDB packaging. `mongoreplay` and its related documentation were then migrated to the read-only [mongodb-labs/mongoreplay](https://github.com/mongodb-labs/mongoreplay) repo.

With the exception of this section of the README, this repo was initially created in 2022 as an exact copy of the archived [mongodb-labs/mongoreplay](https://github.com/mongodb-labs/mongoreplay) repo.

An archived version of the documentation can be found [here](https://web.archive.org/web/20200809055846/https://docs.mongodb.com/v4.0/reference/program/mongoreplay/).

## Purpose

`mongoreplay` is a traffic capture and replay tool for MongoDB. It can be used to inspect commands being sent to a MongoDB instance, record them, and replay them back onto another host at a later time.
## Use cases
- Preview how well your database cluster would perform a production workload under a different environment (storage engine, index, hardware, OS, etc.)
- Reproduce and investigate bugs by recording and replaying the operations that trigger them 
- Inspect the details of what an application is doing to a mongo cluster (i.e. a more flexible version of [mongosniff](https://docs.mongodb.org/manual/reference/program/mongosniff/))

## Quickstart

### Building Tools
To build the tools, you need to have Go version 1.9 and up. `go get` will not work; you
need to clone the repository to build it.

```
git clone https://github.com/mongodb-labs/mongoreplay.git
cd mongodb-labs/mongoreplay.git
```

To use build/test scripts in the repo, you *MUST* set GOROOT to your Go root directory.

```
export GOROOT=/usr/local/go
```

### Quick build

The `build.sh` script builds all the tools, placing them in the `bin`
directory.  Pass any build tags (like `ssl` or `sasl`) as additional command
line arguments.

```
./build.sh
./build.sh ssl
./build.sh ssl sasl
```

### Manual Build

Source `set_goenv.sh` and run the `set_goenv` function to setup your GOPATH and
architecture-specific configuration flags:

```
. ./set_goenv.sh
set_goenv
```

Set the environment variable to use local vendor folder 
Pass tags to the `go build` command as needed in order to build the tools with
support for SSL and/or SASL. For example:

```
mkdir bin
export GO111MODULE=on
export GOSUMDB=off
export GOFLAGS=-mod=vendor
n
go build -o bin/mongoreplay main/mongoreplay.go
go build -o bin/mongoreplay -tags ssl main/mongoreplay.go
go build -o bin/mongoreplay -tags "ssl sasl" main/mongoreplay.go
```

### Use Mongoreplay
Please follow the instructions in https://docs.mongodb.com/manual/reference/program/mongoreplay/.
 
 ## Testing

To run unit and integration tests:

```
./runTests.sh
```
If TOOLS_TESTING_UNIT is set to "true" in the environment, unit tests will run. Delete the environment variable will disable unittest test.
If TOOLS_TESTING_INTEGRATION is set to "true" in the environment, integration tests will run. Delete the environment variable will disable integration test.

Integration tests require a `mongod` (running on port 33333) while unit tests do not.

To run the tests inside pcap_test.go, you need to download the testing pcap files from Amazon S3 to mongoreplay/testPcap
bucket: boxes.10gen.com
path: build/mongotape/
If the pcap files are not available, the tests inside pcap_test will be skpped.
