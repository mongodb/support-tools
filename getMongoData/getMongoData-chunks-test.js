// Run from getMongoData/ against a disposable standalone:
// mongosh <uri> --quiet --file getMongoData-chunks-test.js
load("getMongoData.js");

(function () {
    var originalGetSiblingDB = db.getSiblingDB;
    var originalPrintInfo = printInfo;
    var originalPrintChunkDetails = _printChunkDetails;
    var fixtureDB = db.getSiblingDB("getMongoData_chunks_test_" + ObjectId().toHexString());
    var namespace = "example.data";
    var uuid = UUID("00000000-0000-0000-0000-000000000001");
    var otherUUID = UUID("00000000-0000-0000-0000-000000000002");
    var passed = 0;

    function assertEqual(actual, expected, message) {
        if (JSON.stringify(actual) !== JSON.stringify(expected)) {
            throw new Error(message + ": expected " + JSON.stringify(expected) +
                ", got " + JSON.stringify(actual));
        }
    }

    function chunk(id, fields, min, shard, jumbo) {
        var doc = { _id: id, min: { x: min }, max: { x: min + 1 }, shard: shard };
        Object.keys(fields).forEach(function (key) { doc[key] = fields[key]; });
        if (jumbo !== undefined) doc.jumbo = jumbo;
        return doc;
    }

    var legacyChunks = [
        chunk("legacy-2", { ns: namespace }, 1, "shardB", true),
        chunk("legacy-1", { ns: namespace }, 0, "shardA")
    ];
    var uuidChunks = [
        chunk("uuid-2", { uuid: uuid }, 1, "shardB", true),
        chunk("uuid-1", { uuid: uuid }, 0, "shardA")
    ];
    var mixedChunks = [
        chunk("both", { ns: namespace, uuid: uuid }, 2, "shardA", false),
        legacyChunks[0],
        uuidChunks[1]
    ];
    var cases = [
        { title: "namespace metadata without collection UUID", chunks: legacyChunks },
        { title: "namespace chunks with collection UUID", uuid: uuid, chunks: legacyChunks },
        { title: "UUID-only chunks", uuid: uuid, chunks: uuidChunks },
        { title: "mixed namespace and UUID chunks counted once", uuid: uuid, chunks: mixedChunks },
        { title: "empty result without collection UUID", chunks: [] },
        { title: "empty result with collection UUID", uuid: uuid, chunks: [] }
    ];

    try {
        // Redirect only config lookups; never write to the deployment's config database.
        db.getSiblingDB = function (name) {
            assertEqual(name, "config", "config lookup");
            return fixtureDB;
        };
        var report;
        printInfo = function (message, command) {
            if (message === "Sharded databases") report = command();
        };

        cases.forEach(function (testCase) {
            fixtureDB.databases.deleteMany({});
            fixtureDB.collections.deleteMany({});
            fixtureDB.chunks.deleteMany({});
            fixtureDB.tags.deleteMany({});

            fixtureDB.databases.insertOne({ _id: "example", primary: "shardA", partitioned: true });
            var collection = { _id: namespace, key: { x: 1 }, unique: false };
            if (testCase.uuid !== undefined) collection.uuid = testCase.uuid;
            fixtureDB.collections.insertMany([
                collection,
                { _id: "example.other", key: { x: 1 }, unique: false, uuid: otherUUID },
                { _id: "example.dropped", dropped: true },
                { _id: "exampleX.data", key: { x: 1 } }
            ]);
            var unrelatedChunks = [
                chunk("unrelated-ns", { ns: "example.other" }, 10, "shardC"),
                chunk("unrelated-uuid", { uuid: otherUUID }, 11, "shardC")
            ];
            fixtureDB.chunks.insertMany(testCase.chunks.concat(unrelatedChunks));
            fixtureDB.tags.insertOne({
                ns: namespace, tag: "zoneA", min: { x: 0 }, max: { x: 3 }
            });

            [false, true].forEach(function (details) {
                _printChunkDetails = details;
                report = undefined;
                printShardInfo();
                assertEqual(report.length, 1, testCase.title + ": database count");
                assertEqual(report[0].collections.length, 2, testCase.title + ": collection filtering");
                var result = report[0].collections[0];
                assertEqual(result._id, namespace, "namespace retained");
                assertEqual(result.key, { x: 1 }, "shard key retained");
                assertEqual(result.unique, false, "unique retained");
                var expectedDistribution = testCase.chunks.length === 0 ? [] : [
                    { shard: "shardA", nChunks: testCase.chunks.length === 3 ? 2 : 1 },
                    { shard: "shardB", nChunks: 1 }
                ];
                result.distribution.sort(function (a, b) {
                    return a.shard < b.shard ? -1 : a.shard > b.shard ? 1 : 0;
                });
                assertEqual(result.distribution, expectedDistribution, testCase.title + ": distribution");
                assertEqual(Object.prototype.hasOwnProperty.call(result, "chunks"), details,
                    testCase.title + ": optional chunk field");
                if (details) {
                    var expectedChunks = testCase.chunks.slice().sort(function (a, b) {
                        return a.min.x - b.min.x;
                    }).map(function (doc) {
                        return { min: doc.min, max: doc.max, shard: doc.shard, jumbo: !!doc.jumbo };
                    });
                    assertEqual(result.chunks, expectedChunks, testCase.title + ": sorted chunk details");
                }
                assertEqual(result.tags, [{ tag: "zoneA", min: { x: 0 }, max: { x: 3 } }],
                    "tags retained");
                var other = report[0].collections[1];
                assertEqual(other._id, "example.other", "second collection");
                assertEqual(other.distribution, [{ shard: "shardC", nChunks: 2 }],
                    "per-collection chunk matching");
                if (details) {
                    assertEqual(other.chunks, [
                        { min: { x: 10 }, max: { x: 11 }, shard: "shardC", jumbo: false },
                        { min: { x: 11 }, max: { x: 12 }, shard: "shardC", jumbo: false }
                    ], "second collection chunk details");
                } else {
                    assertEqual(Object.prototype.hasOwnProperty.call(other, "chunks"), false,
                        "second collection omits chunk details");
                }
                passed++;
                print("PASS: " + testCase.title + " (chunk details " + details + ")");
            });
        });
        print("Passed " + passed + " chunk regression cases on MongoDB " + fixtureDB.version());
    } finally {
        db.getSiblingDB = originalGetSiblingDB;
        printInfo = originalPrintInfo;
        _printChunkDetails = originalPrintChunkDetails;
        fixtureDB.dropDatabase();
    }
}());
