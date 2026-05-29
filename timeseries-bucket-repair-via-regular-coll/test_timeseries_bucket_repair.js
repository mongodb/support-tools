// test_timeseries_bucket_repair.js
//
// Integration tests for timeseries_bucket_repair.js.
// Must be run from the directory containing both files, against a replica set.
//
// Usage:
//   mongosh <uri> --file test_timeseries_bucket_repair.js
// or from inside mongosh:
//   load("test_timeseries_bucket_repair.js")

load("timeseries_bucket_repair.js");

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

// Switch the global db to our isolated test database so all calls inside the
// repair functions (which reference `db` directly) operate on it.
const TEST_DB = "ts_bucket_repair_test_" + Date.now();
db = db.getSiblingDB(TEST_DB);

const TS_COLL   = "events";
const SRC_COLL  = "bucket_dump";
const TEMP_COLL = "tmp_repair";

function teardown() {
    for (const c of [TS_COLL, SRC_COLL, TEMP_COLL]) {
        db.getCollection(c).drop();
    }
}

// ---------------------------------------------------------------------------
// TEST 1 — HAPPY PATH
// ---------------------------------------------------------------------------

function testHappyPath() {
    print("\n=== TEST 1: valid bucket in regular collection repairs into TS collection ===");

    db.createCollection(TS_COLL, {timeseries: {timeField: "t", metaField: "host"}});
    db.getCollection(TS_COLL).insertOne({t: new Date("2024-01-01T00:00:00Z"), host: "a", v: 1});

    const bucket = db.getCollection("system.buckets." + TS_COLL).findOne();
    assert(bucket !== null, "bucket exists after insert");

    // Copy bucket to regular collection; reset TS collection to empty.
    db.getCollection(SRC_COLL).insertOne(bucket);
    db.getCollection(TS_COLL).drop();
    db.createCollection(TS_COLL, {timeseries: {timeField: "t", metaField: "host"}});

    const result = repairTimeseriesBucketViaRegularColl(bucket._id, SRC_COLL, TS_COLL, TEMP_COLL);

    assertEqual(result, true, "returns true on success");
    assert(db.getCollection("system.buckets." + TS_COLL).countDocuments() > 0,
        "destination has buckets after repair");
    assertEqual(db.getCollection(TS_COLL).countDocuments(), 1, "measurement is queryable after repair");
    assertEqual(db.getCollection(TEMP_COLL).countDocuments(), 0, "temp collection cleaned up");

    teardown();
}

// ---------------------------------------------------------------------------
// TEST 2 — MISSING SOURCE BUCKET
// ---------------------------------------------------------------------------
// When the bucket _id is not present in the source collection the script
// prints a message and skips it; the destination is left unchanged.

function testMissingSourceBucket() {
    print("\n=== TEST 2: missing source bucket is skipped, destination unchanged ===");

    db.createCollection(TS_COLL, {timeseries: {timeField: "t", metaField: "host"}});
    db.getCollection(TS_COLL).insertOne({t: new Date("2024-02-01T00:00:00Z"), host: "b", v: 2});

    const destCountBefore = db.getCollection("system.buckets." + TS_COLL).countDocuments();

    // Pass a random ObjectId that does not exist in the (empty) source collection.
    repairTimeseriesBucketViaRegularColl(new ObjectId(), SRC_COLL, TS_COLL, TEMP_COLL);

    assertEqual(db.getCollection("system.buckets." + TS_COLL).countDocuments(), destCountBefore,
        "destination bucket count unchanged after skipped repair");
    assertEqual(db.getCollection(TS_COLL).countDocuments(), 1,
        "measurement count unchanged after skipped repair");
    assertEqual(db.getCollection(TEMP_COLL).countDocuments(), 0, "temp collection cleaned up");

    teardown();
}

// ---------------------------------------------------------------------------
// TEST 3 — ARRAY OF BUCKET IDs
// ---------------------------------------------------------------------------

function testMultipleBuckets() {
    print("\n=== TEST 3: array of bucket _ids repairs all of them ===");

    db.createCollection(TS_COLL, {timeseries: {timeField: "t", metaField: "host"}});
    const t0 = new Date("2024-03-01T00:00:00Z");
    // Use different meta values to guarantee separate buckets.
    db.getCollection(TS_COLL).insertMany([
        {t: t0,                             host: "x", v: 10},
        {t: new Date(t0.getTime() + 60000), host: "y", v: 20},
    ]);

    const buckets = db.getCollection("system.buckets." + TS_COLL).find().toArray();
    assert(buckets.length >= 1, "at least one bucket created");

    db.getCollection(SRC_COLL).insertMany(buckets);
    db.getCollection(TS_COLL).drop();
    db.createCollection(TS_COLL, {timeseries: {timeField: "t", metaField: "host"}});

    const result = repairTimeseriesBucketViaRegularColl(
        buckets.map(b => b._id), SRC_COLL, TS_COLL, TEMP_COLL);

    assertEqual(result, true, "returns true");
    assertEqual(db.getCollection(TS_COLL).countDocuments(), 2, "all measurements queryable after repair");
    assertEqual(db.getCollection(TEMP_COLL).countDocuments(), 0, "temp collection cleaned up");

    teardown();
}

// ---------------------------------------------------------------------------
// TEST 4 — TEMP COLLECTION OPTIONS MISMATCH
// ---------------------------------------------------------------------------
// If the temp collection already exists with different options the script
// must throw rather than silently producing wrong results.

function testTempCollOptionsMismatch() {
    print("\n=== TEST 4: temp collection with wrong options throws ===");

    db.createCollection(TS_COLL, {timeseries: {timeField: "t", metaField: "host"}});
    // Create temp collection with a different timeField.
    db.createCollection(TEMP_COLL, {timeseries: {timeField: "ts", metaField: "host"}});

    let threw = false;
    try {
        repairTimeseriesBucketViaRegularColl(new ObjectId(), SRC_COLL, TS_COLL, TEMP_COLL);
    } catch (e) {
        threw = true;
    }
    assert(threw, "throws when temp collection has mismatched options");

    teardown();
}

// ---------------------------------------------------------------------------
// TEST 5 — CORRUPT CONTROL FIELDS REPAIRED (7.0+)
// ---------------------------------------------------------------------------

function testCorruptControlField() {
    print("\n=== TEST 5: corrupt control.max.t is repaired ===");

    const [major] = serverVersion();
    if (major < 7) {
        print(`  SKIP  Server ${db.version()} < 7.0: control-field validation not enforced on direct insert.`);
        return;
    }

    db.createCollection(TS_COLL, {timeseries: {timeField: "t", metaField: "host"}});
    db.getCollection(TS_COLL).insertOne({t: new Date("2024-04-01T12:00:00Z"), host: "c", v: 42});

    const validBucket = db.getCollection("system.buckets." + TS_COLL).findOne();
    const corruptBucket = Object.assign({}, validBucket, {
        control: Object.assign({}, validBucket.control, {
            max: Object.assign({}, validBucket.control.max, {t: new Date(0)}),
        }),
    });

    db.getCollection(SRC_COLL).insertOne(corruptBucket);
    db.getCollection(TS_COLL).drop();
    db.createCollection(TS_COLL, {timeseries: {timeField: "t", metaField: "host"}});

    const result = repairTimeseriesBucketViaRegularColl(corruptBucket._id, SRC_COLL, TS_COLL, TEMP_COLL);

    assertEqual(result, true, "returns true");
    assertEqual(db.getCollection(TS_COLL).countDocuments(), 1, "measurement queryable after repair");
    const doc = db.getCollection(TS_COLL).findOne({host: "c"});
    assert(doc !== null, "measurement findable by meta");
    if (doc !== null) assertEqual(doc.v, 42, "measurement value preserved through repair");

    teardown();
}

// ---------------------------------------------------------------------------
// RUN ALL TESTS
// ---------------------------------------------------------------------------

print(`\nRunning against database: ${TEST_DB}  (server ${db.version()})`);
print("=".repeat(60));

testHappyPath();
testMissingSourceBucket();
testMultipleBuckets();
testTempCollOptionsMismatch();
testCorruptControlField();

print("\n" + "=".repeat(60));
print(`Results: ${_passed} passed, ${_failed} failed`);
print(_failed > 0 ? "RESULT: FAILED" : "RESULT: ALL TESTS PASSED");

db.dropDatabase();
