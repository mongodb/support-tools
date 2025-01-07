
// ---------------------------------------------------------------------------------------
// The script will, for each bucket in the affected time-series collection:
// 1) Detect if the bucket has a mismatch between the embedded bucket id
// timestamp and the control min timestamp.
// 2) Re-insert the measurements of the timestamp-mismatched bucket
// transactionally.
//    a) Unpack the measurements
//    b) Insert the measurements back into the collection. These will go into
//    new buckets.
//    c) Delete the mixed-schema bucket from the collection.
// 3) Validate that there are no buckets with a mismatch between the embedded
// bucket id timestamp and the control min timestamp.
// 4) Tell the server there aren't buckets with a mismatch between the embedded
// bucket id timestamp and the control min timestamp.
// ----------------------------------------------------------------------------------------
let bucketColl;
let tsOptions;
let tempTimeseriesColl;
let tempTimeseriesBucketsColl;

function setUp() {
  bucketColl = db.getCollection('system.buckets.' + collName);

  // Create a temp collection to store measurements from the mixed-schema
  // buckets.
  tsOptions =
      db.runCommand({listCollections: 1.0, filter: {name: coll.getName()}})
          .cursor.firstBatch[0]
          .options.timeseries;

  db.createCollection('temp', {timeseries: tsOptions});
  tempTimeseriesColl = db.getCollection('temp');
  tempTimeseriesBucketsColl = db.getCollection('system.buckets.temp');
}

// Main function.
function runFixEmbeddedBucketIdControlMinMismatchProcedure() {
  setUp();
  print(
      'Finding when embedded bucket ID timestamps don\'t match the control min timestamps in  ' +
      collName + ' ...\n');
  let cursor = bucketsColl.find({}, {_id: true, control: true});

  // Mismatched timestamp buckets will have different types for their
  // control.min.parameter and control.max.parameter due to type ordering.
  // Iterate through all buckets, checking if the control.min and control.max
  // types match. If they do not match, re-insert the bucket.
  while (cursor.hasNext()) {
    const bucket = cursor.next();
    const bucketId = bucket._id;
    const controlMinTimestamp = bucket.control.min

    if (bucketHasMismatchedEmbeddedBucketIdAndControlMin(
            bucketId, controlMinTimestamp)) {
      reinsertMeasurementsFromBucket(bucket._id);
    }
  }
}

function getDateFromObjectId(objectId) {
  return new Date(parseInt(objectId.substring(0, 8), 16) * 1000);
}

//
// Helpers to detect whether a given bucket contains a mismatch between the
// embedded bucket id timestamp and the control min timestamp.
//
// We parse each timestamp to a date and use .getTime() to compare them.
//
function bucketHasMismatchedEmbeddedBucketIdAndControlMin(
    bucketId, controlMinTime) {
  const oidTimestamp = getDateFromObjectId(bucketId)
  const controlMinTimestamp = new Date(Date.parse(controlMinTime));
  return oidTimestamp.getTime() == controlMinTimestamp.getTime()
}

//
// Helpers to perform the re-insertion procedure.
//
function reinsertMeasurementsFromBucket(bucketId) {
  print('Re-inserting measurements from bucket ' + bucketId + '...\n');

  // Prevent concurrent changes on this bucket by setting control.closed.
  bucketColl.updateOne({_id: bucketId}, {$set: {'control.closed': true}});

  // Get the measurements from the mixed-schema bucket.
  print('Getting the measurements from the mixed-schema bucket...\n');
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
