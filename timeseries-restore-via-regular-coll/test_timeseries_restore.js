// test_timeseries_restore.js
//
// Integration tests for timeseries-restore-via-regular-coll.js.
// Must be run from the directory containing both files, against a replica set.
//
// Usage:
//   mongosh <uri> --file test_timeseries_restore.js
// or from inside mongosh:
//   load("test_timeseries_restore.js")

load("timeseries-restore-via-regular-coll.js");

// ---------------------------------------------------------------------------
// TINY TEST RUNNER
// ---------------------------------------------------------------------------

let _passed = 0;
let _failed = 0;

function assert(condition, msg) {
    if (!condition) {
        print(`  FAIL  ${msg}`);
        _failed++;
    } else {
        print(`  pass  ${msg}`);
        _passed++;
    }
}

function assertEqual(actual, expected, msg) {
    if (actual !== expected) {
        print(`  FAIL  ${msg} — expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
        _failed++;
    } else {
        print(`  pass  ${msg}`);
        _passed++;
    }
}

function serverVersion() {
    const v = db.version().split(".").map(Number);
    return [v[0], v[1] || 0];
}

// ---------------------------------------------------------------------------
// SHARED TEST HELPERS
// ---------------------------------------------------------------------------

const TEST_DB = "ts_restore_test_" + Date.now();
const testDb  = db.getSiblingDB(TEST_DB);

const SRC_COLL = "src_buckets";
const TMP_COLL = "tmp_repair";
const BAD_COLL = "bad_buckets";

// Dumps all bucket docs from system.buckets into SRC_COLL, then drops and
// recreates the TS collection empty so there is something to restore.
function dumpBucketsAndReset(tsCollName) {
    const tsOptions = testDb.getCollectionInfos({name: tsCollName})[0].options.timeseries;
    const buckets = testDb.getCollection("system.buckets." + tsCollName).find().toArray();
    if (buckets.length > 0) {
        testDb.getCollection(SRC_COLL).insertMany(buckets);
    }
    testDb.getCollection(tsCollName).drop();
    testDb.createCollection(tsCollName, {timeseries: tsOptions});
}

function teardown(tsCollName) {
    for (const coll of [tsCollName, SRC_COLL, TMP_COLL, BAD_COLL]) {
        testDb.getCollection(coll).drop();
    }
}

// ---------------------------------------------------------------------------
// TEST 1 — HAPPY PATH
// ---------------------------------------------------------------------------

function testHappyPath() {
    print("\n=== TEST 1: Happy path (valid buckets insert directly) ===");
    const tsCollName = "events_happy";
    testDb.createCollection(tsCollName, {timeseries: {timeField: "t", metaField: "host"}});
    const tsColl = testDb.getCollection(tsCollName);

    const t0 = new Date("2024-01-01T00:00:00Z");
    tsColl.insertMany([
        {t: t0,                              host: "a", v: 1},
        {t: new Date(t0.getTime() + 60000),  host: "b", v: 2},
        {t: new Date(t0.getTime() + 120000), host: "a", v: 3},
    ]);

    const bucketsBefore = testDb.getCollection("system.buckets." + tsCollName).countDocuments();
    assert(bucketsBefore > 0, "inserting measurements creates at least one bucket");

    dumpBucketsAndReset(tsCollName);
    assertEqual(testDb.getCollection(SRC_COLL).countDocuments(), bucketsBefore,
        "srcBucketsColl has all original bucket docs");
    assertEqual(testDb.getCollection("system.buckets." + tsCollName).countDocuments(), 0,
        "destination is empty after reset");

    const result = runCopyWithRepair(testDb, SRC_COLL, tsCollName, TMP_COLL, BAD_COLL, 1000);

    assertEqual(testDb.getCollection(SRC_COLL).countDocuments(), 0, "src is empty after restore");
    assertEqual(testDb.getCollection(BAD_COLL).countDocuments(), 0, "no bad buckets");
    assertEqual(testDb.getCollection("system.buckets." + tsCollName).countDocuments(), bucketsBefore,
        "destination has all buckets restored");
    assertEqual(result.totalBad,      0, "totalBad = 0");
    assertEqual(result.totalRepaired, 0, "totalRepaired = 0");
    assertEqual(tsColl.countDocuments(), 3, "all 3 measurements are queryable");

    teardown(tsCollName);
}

// ---------------------------------------------------------------------------
// TEST 2 — REPAIR PATH
// ---------------------------------------------------------------------------
// Creates a bucket with control.max.t set to epoch (1970-01-01), violating
// the control.max >= actual_max invariant.  On MongoDB 7.0+ this causes the
// direct insert into system.buckets to fail validation, forcing the repair
// path.  The repair aggregation unpacks the real measurements from the data
// columns and re-packs them into a fresh, valid bucket.

function testRepairPath() {
    print("\n=== TEST 2: Repair path (corrupt control fields repaired via unpack+$out) ===");

    const [major] = serverVersion();
    if (major < 7) {
        print(`  SKIP  Server ${db.version()} < 7.0: control-field validation on direct ` +
              `system.buckets inserts is not enforced; direct insert would succeed, bypassing repair.`);
        return;
    }

    const tsCollName = "events_repair";
    testDb.createCollection(tsCollName, {timeseries: {timeField: "t", metaField: "host"}});
    const tsColl = testDb.getCollection(tsCollName);

    const t0 = new Date("2024-06-01T12:00:00Z");
    tsColl.insertOne({t: t0, host: "x", v: 42});

    const validBucket = testDb.getCollection("system.buckets." + tsCollName).findOne();
    assert(validBucket !== null, "a bucket was created");

    // Corrupt: set control.max.t to epoch so it claims the maximum measurement
    // time is 1970 — clearly before the real measurement in 2024.
    const corruptBucket = Object.assign({}, validBucket);
    corruptBucket.control     = Object.assign({}, validBucket.control);
    corruptBucket.control.max = Object.assign({}, validBucket.control.max);
    corruptBucket.control.max.t = new Date(0);

    testDb.getCollection(SRC_COLL).insertOne(corruptBucket);

    // Read tsOptions before dropping so we can recreate with the identical spec.
    const tsOptions = testDb.getCollectionInfos({name: tsCollName})[0].options.timeseries;
    testDb.getCollection(tsCollName).drop();
    testDb.createCollection(tsCollName, {timeseries: tsOptions});

    const result = runCopyWithRepair(testDb, SRC_COLL, tsCollName, TMP_COLL, BAD_COLL, 1000);

    assertEqual(testDb.getCollection(SRC_COLL).countDocuments(), 0, "src is empty after restore");
    assertEqual(testDb.getCollection(BAD_COLL).countDocuments(), 0, "bucket was repaired, not marked bad");
    assert(result.totalRepaired >= 1,                                "at least one bucket went through repair");
    assertEqual(result.totalBad, 0,                                  "totalBad = 0");
    assertEqual(tsColl.countDocuments(), 1,                          "repaired measurement is queryable");
    const doc = tsColl.findOne({host: "x"});
    assert(doc !== null, "measurement with host=x is findable");
    if (doc !== null) assertEqual(doc.v, 42, "measurement value is preserved through repair");

    teardown(tsCollName);
}

// ---------------------------------------------------------------------------
// TEST 3 — UNRECOVERABLE BUCKET
// ---------------------------------------------------------------------------
// A document missing the `data` column-store field fails both direct insert
// and the repair aggregation (nothing to unpack), so it ends up in
// badBucketsColl.

function testUnrecoverableBucket() {
    print("\n=== TEST 3: Unrecoverable bucket (recorded in badBucketsColl) ===");
    const tsCollName = "events_bad";
    testDb.createCollection(tsCollName, {timeseries: {timeField: "t", metaField: "host"}});

    const badId = new ObjectId();
    testDb.getCollection(SRC_COLL).insertOne({
        _id: badId,
        control: {version: 1, min: {t: new Date()}, max: {t: new Date()}},
        // data field intentionally absent — nothing to unpack
    });

    const result = runCopyWithRepair(testDb, SRC_COLL, tsCollName, TMP_COLL, BAD_COLL, 1000);

    assertEqual(testDb.getCollection(SRC_COLL).countDocuments(), 0, "src is empty after processing");
    assertEqual(testDb.getCollection(BAD_COLL).countDocuments(), 1, "unrecoverable bucket is in badBucketsColl");
    assertEqual(result.totalBad,      1,                             "totalBad = 1");
    assertEqual(result.totalRepaired, 0,                             "totalRepaired = 0");

    const badRecord = testDb.getCollection(BAD_COLL).findOne({_id: badId});
    assert(badRecord !== null,                     "bad record is findable by original _id");
    assert(badRecord.originalBucket !== undefined, "bad record preserves the original bucket doc");
    assert(badRecord.error !== undefined,          "bad record contains error info");

    teardown(tsCollName);
}

// ---------------------------------------------------------------------------
// TEST 4 — RE-RUN IDEMPOTENCY
// ---------------------------------------------------------------------------
// Running against the same source data twice must be a no-op on the second
// run: every insertOne into the destination gets DuplicateKey (treated as
// success), the source is emptied, and measurement counts are unchanged.

function testIdempotency() {
    print("\n=== TEST 4: Re-run idempotency ===");
    const tsCollName = "events_idempotent";
    testDb.createCollection(tsCollName, {timeseries: {timeField: "t", metaField: "host"}});
    const tsColl = testDb.getCollection(tsCollName);

    const t0 = new Date("2024-03-01T00:00:00Z");
    tsColl.insertMany([
        {t: t0,                             host: "a", v: 10},
        {t: new Date(t0.getTime() + 60000), host: "a", v: 20},
    ]);

    const originalBuckets = testDb.getCollection("system.buckets." + tsCollName).find().toArray();
    dumpBucketsAndReset(tsCollName);

    // First run — all buckets copy directly.
    const result1 = runCopyWithRepair(testDb, SRC_COLL, tsCollName, TMP_COLL, BAD_COLL, 1000);
    assertEqual(testDb.getCollection(SRC_COLL).countDocuments(), 0, "src empty after run 1");
    assertEqual(result1.totalBad, 0,                                "no bad buckets after run 1");

    const destCountAfterRun1 = testDb.getCollection("system.buckets." + tsCollName).countDocuments();

    // Repopulate source with the same bucket docs to simulate a re-run.
    testDb.getCollection(SRC_COLL).insertMany(originalBuckets);

    // Second run — every insertOne hits DuplicateKey, treated as success.
    const result2 = runCopyWithRepair(testDb, SRC_COLL, tsCollName, TMP_COLL, BAD_COLL, 1000);

    assertEqual(testDb.getCollection(SRC_COLL).countDocuments(), 0, "src empty after run 2");
    assertEqual(result2.totalBad, 0,                                "no bad buckets after run 2");
    assertEqual(
        testDb.getCollection("system.buckets." + tsCollName).countDocuments(),
        destCountAfterRun1,
        "destination bucket count is unchanged after second run"
    );
    assertEqual(tsColl.countDocuments(), 2, "measurement count is not doubled after second run");

    teardown(tsCollName);
}

// ---------------------------------------------------------------------------
// TEST 5 — bucketRoundingSeconds PRESERVED IN REPAIR SPEC
// ---------------------------------------------------------------------------
// Regression for the bug where makeTimeseriesOutSpec omitted
// bucketRoundingSeconds.  Also verifies a full restore round-trip with
// custom rounding options.

function testBucketRoundingSeconds() {
    print("\n=== TEST 5: bucketRoundingSeconds preserved in $out spec ===");

    const [major, minor] = serverVersion();
    if (major < 6 || (major === 6 && minor < 3)) {
        print(`  SKIP  Server ${db.version()} < 6.3: bucketRoundingSeconds not supported.`);
        return;
    }

    const tsCollName = "events_rounding";
    testDb.createCollection(tsCollName, {
        timeseries: {timeField: "t", metaField: "host", bucketMaxSpanSeconds: 3600, bucketRoundingSeconds: 3600},
    });
    const tsColl    = testDb.getCollection(tsCollName);
    const tsOptions = testDb.getCollectionInfos({name: tsCollName})[0].options.timeseries;

    // Unit check: makeTimeseriesOutSpec (from the loaded script) must include
    // bucketRoundingSeconds.  Use Number() to normalise BSON Int32 vs JS number.
    const outSpec = makeTimeseriesOutSpec(tsOptions);
    assertEqual(Number(outSpec.bucketRoundingSeconds), 3600,
        "makeTimeseriesOutSpec includes bucketRoundingSeconds");
    assertEqual(Number(outSpec.bucketMaxSpanSeconds), 3600,
        "makeTimeseriesOutSpec includes bucketMaxSpanSeconds");

    // Full round-trip.
    tsColl.insertOne({t: new Date("2024-01-01T00:30:00Z"), host: "z", v: 99});
    dumpBucketsAndReset(tsCollName);

    const result = runCopyWithRepair(testDb, SRC_COLL, tsCollName, TMP_COLL, BAD_COLL, 1000);

    assertEqual(testDb.getCollection(SRC_COLL).countDocuments(), 0, "src empty after restore");
    assertEqual(result.totalBad, 0,                                  "no bad buckets");
    assertEqual(tsColl.countDocuments(), 1,                          "measurement is queryable after restore");
    const doc = tsColl.findOne({host: "z"});
    assert(doc !== null,   "measurement is findable");
    assertEqual(doc.v, 99, "measurement value preserved");

    teardown(tsCollName);
}

// ---------------------------------------------------------------------------
// RUN ALL TESTS
// ---------------------------------------------------------------------------

print(`\nRunning against database: ${TEST_DB}  (server ${db.version()})`);
print("=".repeat(60));

testHappyPath();
testRepairPath();
testUnrecoverableBucket();
testIdempotency();
testBucketRoundingSeconds();

print("\n" + "=".repeat(60));
print(`Results: ${_passed} passed, ${_failed} failed`);
print(_failed > 0 ? "RESULT: FAILED" : "RESULT: ALL TESTS PASSED");

testDb.dropDatabase();
