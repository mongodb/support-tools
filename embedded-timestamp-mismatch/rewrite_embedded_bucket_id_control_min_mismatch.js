// ------------------------------------------------------------------------------------
// Populate collName with the time-series collection with a bucket(s) that has
// mismatched embedded bucket id timestamp and control.min timestamp.
// ------------------------------------------------------------------------------------
const collName = 'your_collection_name';

let listCollectionsRes = db.runCommand({
                             listCollections: 1.0,
                             filter: {name: collName}
                           }).cursor.firstBatch;
if (listCollectionsRes.length == 0) {
  print(
      'Collection not found. Populate collName with the time-series collection with a bucket(s) that has mismatched embedded bucket id timestamp and control.min timestamp.');
  exit(1);
}
const coll = db.getCollection(collName);
const bucketsColl = db.getCollection('system.buckets.' + collName);

//
// NON-MODIFIABLE CODE BELOW
//
// ------------------------------------------------------------------------------------
// The "temp" collection should not exist prior to running the script. This will
// be used for storing the measurements of the buckets with mismatched embedded
// bucket id timestamp and control.min timestamp.
// ------------------------------------------------------------------------------------
listCollectionsRes = db.runCommand({
                         listCollections: 1.0,
                         filter: {name: 'temp'}
                       }).cursor.firstBatch;
if (listCollectionsRes.length != 0) {
  print(
      'Collection `temp` should not exist prior to running the script. Rename or drop the collection before running this script');
  exit(1);
}

// ---------------------------------------------------------------------------------------
// The script will, for each bucket in the affected time-series collection:
// 1) Detect if the bucket has a mismatch between the embedded bucket id
// timestamp and the control min timestamp.
// 2) Re-insert the measurements of the timestamp-mismatched bucket
// transactionally.
//    a) Unpack the measurements
//    b) Repack the measurements into new buckets.
//    c) Delete the original, problematic bucket from the collection.
// 3) Validate that there are no buckets with a mismatch between the embedded
// bucket id timestamp and the control min timestamp.
// ----------------------------------------------------------------------------------------
let bucketColl;
let tsOptions;
let tempTimeseriesColl;
let tempTimeseriesBucketsColl;

function setUp() {
  bucketColl = db.getCollection('system.buckets.' + collName);

  // Create a temp collection to store measurements from the buckets with
  // mismatched embedded bucket id timestamp and control.min timestamp.
  tsOptions =
      db.runCommand({listCollections: 1.0, filter: {name: coll.getName()}})
          .cursor.firstBatch[0]
          .options.timeseries;

  db.createCollection('temp', {timeseries: tsOptions});
  tempTimeseriesColl = db.getCollection('temp');
  tempTimeseriesBucketsColl = db.getCollection('system.buckets.temp');
}

// Helper function to determine if timestamp is in extended range.
function timestampInExtendedRange(timestamp) {
  return timestamp < new Date(ISODate('1970-01-01T00:00:00.000Z')).getTime() ||
      timestamp > new Date(ISODate('2038-01-19T03:14:07.000Z')).getTime()
}

// Main function.
function runFixEmbeddedBucketIdControlMinMismatchProcedure() {
  setUp();
  let cursor = bucketsColl.find({}, {_id: true, control: true});

  // Mismatched timestamp buckets will have different types for their
  // control.min.parameter and control.max.parameter due to type ordering.
  // Iterate through all buckets, checking if the control.min and control.max
  // types match. If they do not match, re-insert the bucket.
  while (cursor.hasNext()) {
    const bucket = cursor.next();
    const oidTimestamp = new Date(bucket._id.getTimestamp()).getTime();
    const controlMinTimestamp = new Date(bucket.control.min.t).getTime();

    // If this collection has extended-range measurements, we cannot assert that
    // the minTimestamp matches the embedded timestamp.
    print(controlMinTimestamp == oidTimestamp)
    if (!timestampInExtendedRange(controlMinTimestamp) &&
        oidTimestamp != controlMinTimestamp) {
      reinsertMeasurementsFromBucket(bucket._id);
    }
  }
}

//
// Helpers to perform the re-insertion procedure.
//
function reinsertMeasurementsFromBucket(bucketId) {
  print('Re-inserting measurements from bucket ' + bucketId + '...\n');

  // Prevent concurrent changes on this bucket by setting control.closed.
  bucketColl.updateOne({_id: bucketId}, {$set: {'control.closed': true}});

  // Get the measurements from the bucket that has a mismatched embedded bucket
  // id timestamp and control.min timestamp.
  let measurements;
  if (tsOptions.metaField) {
    measurements = bucketColl
                       .aggregate([
                         {$match: {_id: bucketId}}, {
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
                         {$match: {_id: bucketId}}, {
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
      print('An error occurred ' + e);
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
      const session = db.getMongo().startSession({retryWrites: true});
      session.startTransaction();

      const sessionBucketColl =
          session.getDatabase(db.getName())
              .getCollection('system.buckets.' + collName);
      sessionBucketColl.deleteOne({_id: bucketId});
      const bucketDocs = tempTimeseriesBucketsColl.find().toArray();
      sessionBucketColl.insertMany(bucketDocs);

      session.commitTransaction();
    } catch (e) {
      if (!shouldRetryTxnOnTransientError(e)) {
        throw e;
      }
      hasTransientError = true;
      print('Encountered a transient error. Retrying transaction.');
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
// Steps 1 & 2: Detect if a bucket has mismatched embedded bucket id timestamps
// and control.min timestamps in the collection and re-inserts buckets with
// these mismatches.
//
print(
    'Re-inserting buckets that have a mismatched embedded bucket id timestamps and control.min timestamps in the collection ...\n');
runFixEmbeddedBucketIdControlMinMismatchProcedure();
tempTimeseriesBucketsColl.drop();

//
// Step 3: Validate that there are no buckets with mismatched embedded bucket id
// timestamps and control.min timestamps in the collection.
//
print(
    'Validating that there are no buckets that have a mismatched embedded bucket id timestamp and control.min timestamp ...\n');
db.getMongo().setReadPref('secondaryPreferred');
const validateRes = coll.validate({background: true});

//
// For v8.1.0+, buckets that have a mismatched embedded bucket id timestamp and
// control.min timestamp will lead to a error during validation.
//
// Prior to v8.1.0, buckets that have a mismatched embedded bucket id timestamp
// and control.min timestamp will lead to a warning during validation.
//
if (validateRes.errors.length != 0 || validateRes.warnings.length != 0) {
  print(
      '\nThere is still a bucket(s) that has a mismatched embedded bucket id timestamps and control.min timestamps, or there is another error or warning during validation.');
  exit(1);
}

print(
    '\nScript successfully fixed buckets with mismatched embedded bucket id timestamp and control.min timestamp!');
exit(0);
