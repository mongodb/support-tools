// ------------------------------------------------------------------------------------
// Populate collName with the time-series collection with mixed-schema buckets.
// ------------------------------------------------------------------------------------
const collName = "your_collection_name";

let listCollectionsRes = db.runCommand({ listCollections: 1.0, filter: { name: collName } }).cursor.firstBatch;
if (listCollectionsRes.length == 0) {
    print("Collection not found. Populate collName with the time-series collection with mixed-schema buckets.");
    exit(1);
}
const coll = db.getCollection(collName);
const bucketsColl = db.getCollection('system.buckets.' + collName);

//
// NON-MODIFIABLE CODE BELOW
// 
// ------------------------------------------------------------------------------------
// The "temp" collection should not exist prior to running the script. This will be used 
// for storing the measurements of the mixed-schema buckets.
// ------------------------------------------------------------------------------------
listCollectionsRes = db.runCommand({ listCollections: 1.0, filter: { name: "temp" } }).cursor.firstBatch;
if (listCollectionsRes.length != 0) {
    print("Collection `temp` should not exist prior to running the script. Rename or drop the collection before running this script");
    exit(1);
}

// ---------------------------------------------------------------------------------------
// The script will, for each bucket in the affected time-series collection:
// 1) Detect if the bucket has mixed-schema data.
// 2) Re-insert the measurements of the mixed-schema bucket transactionally.
//    a) Unpack the measurements
//    b) Insert the measurements back into the collection. These will go into new buckets.
//    c) Delete the mixed-schema bucket from the collection.
// 3) Validate that there are no mixed-schema buckets left.
// 4) Tell the server there is no longer any mixed-schema data.
// ----------------------------------------------------------------------------------------
let bucketColl;
let tsOptions;
let tempTimeseriesColl;
let tempTimeseriesBucketsColl;

function setUp() {
    bucketColl = db.getCollection("system.buckets." + collName);

    // Create a temp collection to store measurements from the mixed-schema buckets.
    tsOptions = db.runCommand({ listCollections: 1.0, filter: { name: coll.getName() } })
        .cursor.firstBatch[0]
        .options.timeseries;

    db.createCollection("temp", { timeseries: tsOptions });
    tempTimeseriesColl = db.getCollection("temp");
    tempTimeseriesBucketsColl = db.getCollection("system.buckets.temp");
}

function runMixedSchemaBucketsReinsertionProcedure() {
    setUp();
    print("Finding mixed schema buckets in collection " + collName + " ...\n");
    let cursor = bucketsColl.find({}, { _id: true, control: true });

    // Mixed-schema buckets will have different types for their  
    // control.min.parameter and control.max.parameter due to type ordering. Iterate through all 
    // buckets, checking if the control.min and control.max types match. 
    // If they do not match, re-insert the bucket.
    while (cursor.hasNext()) {
        const bucket = cursor.next();

        const minFields = bucket.control.min;
        const maxFields = bucket.control.max;

        if (bucketHasMixedSchema(minFields, maxFields)) {
            reinsertMeasurementsFromBucket(bucket._id);
        }
    }
}

//
// Helpers to detect whether a given bucket contains mixed-schema data. Mixed-schema buckets will
// have different canonical types for their control.min.parameter and control.max.parameter because
// of type ordering.
//
// To do this check, we first must find the canonical value of the field, as a false positive may be
// thrown, e.g. if there is a bucket field has measurements that are decimals and integers.
//
function bucketHasMixedSchema(minFields, maxFields) {
    for (let field in minFields) {
        if (!compareCanonicalTypes(minFields[field], maxFields[field])) {
            return true;
        } else if (canonicalizeType(minFields[field]) == "object" ||
            canonicalizeType(minFields[field]) == "array") {
            // Canonical types are equal, but we still may need to recurse to check the nested
            // object/array's elements.
            if (bucketHasMixedSchema(minFields[field], maxFields[field])) {
                return true;
            }
        }
    }

    return false;
}

function canonicalizeType(field) {
    let type = typeof field;

    if (type == "object") {
        if (field instanceof NumberDecimal || field instanceof NumberLong) {
            return "number";
        } else if (field instanceof ObjectId) {
            return "objectId";
        } else if (field instanceof Date) {
            return "date";
        } else if (field instanceof Timestamp) {
            return "timestamp";
        } else if (Array.isArray(field)) {
            return "array";
        } else if (field instanceof BinData) {
            return "binData";
        } else if (field instanceof RegExp) {
            return "regex";
        } else if (field === null) {
            return "null";
        }
        return "object";
    } else if (type == "symbol") {
        return "string";
    }
    return type;
}

function compareCanonicalTypes(field, otherField) {
    if (canonicalizeType(field) == canonicalizeType(otherField)) {
        return true;
    }
    return false;
}

//
// Helpers to perform the re-insertion procedure.
//
function reinsertMeasurementsFromBucket(bucketId) {
    print("Re-inserting measurements from bucket " + bucketId + "...\n");

    // Prevent concurrent changes on this bucket by setting control.closed.
    bucketColl.updateOne({ _id: bucketId }, { $set: { 'control.closed': true } });

    // Get the measurements from the mixed-schema bucket.
    print("Getting the measurements from the mixed-schema bucket...\n");
    let measurements;
    if (tsOptions.metaField) {
        measurements = bucketColl
            .aggregate([
                { $match: { _id: bucketId } },
                {
                    $_unpackBucket: {
                        timeField: tsOptions.timeField,
                        metaField: tsOptions.metaField,
                    }
                }
            ])
            .toArray();
    } else {
        measurements = bucketColl
            .aggregate([
                { $match: { _id: bucketId } },
                {
                    $_unpackBucket: {
                        timeField: tsOptions.timeField,
                    }
                }
            ])
            .toArray();
    }

    // To avoid network roundtrips, insert measurements in the 
    // temporary time-series collection in one batch and retry if any errors 
    // are encountered.
    let retryTempInsert;
    do {
        retryTempInsert = false;
        try {
            tempTimeseriesBucketsColl.deleteMany({});
            tempTimeseriesColl.insertMany(measurements);
        } catch (e) {
            print("An error occurred " + e);
            retryTempInsert = true;
        }
    } while (retryTempInsert);

    // Run the bucket re-insertion in a transaction. It is necessary to 
    // interact with the buckets collection because transactions are not
    // supported on the time-series view. 
    // Additionally, we want to retry this transaction on transient errors   
    // since we are touching potentially lots of data, which would cause  
    // excessive cache dirtying.
    let hasTransientError;
    do {
        hasTransientError = false;
        try {
            const session = db.getMongo().startSession({ retryWrites: true });
            session.startTransaction();

            const sessionBucketColl = session.getDatabase(db.getName()).getCollection('system.buckets.' + collName);
            sessionBucketColl.deleteOne({ _id: bucketId });
            const bucketDocs = tempTimeseriesBucketsColl.find().toArray();
            sessionBucketColl.insertMany(bucketDocs);

            session.commitTransaction();
        } catch (e) {
            if (!shouldRetryTxnOnTransientError(e)) {
                throw e;
            }
            hasTransientError = true;
            print("Encountered a transient error. Retrying transaction.");
            continue;
        }
    } while (hasTransientError);
}

function shouldRetryTxnOnTransientError(e) {
    if ((e.hasOwnProperty('errorLabels') &&
        e.errorLabels.includes('TransientTransactionError'))) {
        return true;
    }
    return false;
}

// 
// Steps 1 & 2: Re-insert mixed-schema buckets in the collection.
//
print("Re-inserting mixed-schema buckets in the collection ...\n");
runMixedSchemaBucketsReinsertionProcedure();
tempTimeseriesBucketsColl.drop();

// 
// Step 3: Validate that there are no mixed-schema buckets left.
//
print("Validating that there are no mixed-schema buckets left ...\n");
db.getMongo().setReadPref("secondaryPreferred");
const validateRes = coll.validate();
if (validateRes.warnings.length != 0) {
    print("\nThere is still a time-series bucket with mixed-schema data. Try re-running the script to re-insert the buckets missed.");
    exit(1);
}

//
// Step 4: Tell the server there is no longer any mixed-schema data.
//
db.runCommand({ collMod: collName, timeseriesBucketsMayHaveMixedSchemaData: false });
print("\nScript successfully fixed mixed-schema buckets!");
exit(0);