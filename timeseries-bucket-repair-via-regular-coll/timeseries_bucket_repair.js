// ------------------------------------------------------------------------------------
// This script provides functionality to re-write internal time-series bucket
// documents that are stored in a regular (non-timeseries) MongoDB collection.
// It can be used to repair most types of logical bucket corruption detected by
// validate, when the bucket data has been extracted into a regular collection.
//
// Load this script in mongosh with load(), switch to the target database,
// then call repairTimeseriesBucketViaRegularColl().
// ------------------------------------------------------------------------------------

//
// Helper function to validate namespaces, create the temporary collection, and
// return the timeseries options of the target collection.
//
function verifyAndSetupCollsAndGetTSOptions(tsColl, tempColl) {
  const tsInfo = db.runCommand({listCollections: 1.0, filter: {name: tsColl}})
                    .cursor.firstBatch;
  if (!tsInfo || tsInfo.length === 0) {
    throw new Error(`Collection "${tsColl}" does not exist in db "${db.getName()}".`);
  }
  const tsOptions = tsInfo[0].options && tsInfo[0].options.timeseries;
  if (!tsOptions) {
    throw new Error(`Collection "${tsColl}" is not a timeseries collection.`);
  }

  // Verify that the temp collection has the same options if it already exists.
  const tempRes = db.runCommand({listCollections: 1.0, filter: {name: tempColl}})
                     .cursor.firstBatch;
  if (tempRes && tempRes.length > 0) {
    const tempOptions = tempRes[0].options && tempRes[0].options.timeseries;
    if (!tempOptions ||
        tsOptions.timeField != tempOptions.timeField ||
        tsOptions.metaField != tempOptions.metaField ||
        tsOptions.granularity != tempOptions.granularity ||
        tsOptions.bucketMaxSpanSeconds != tempOptions.bucketMaxSpanSeconds) {
      throw new Error(
          `Temp collection "${tempColl}" exists but has unexpected options. ` +
          `Please specify a different temporary namespace.`);
    }
    db.getCollection(tempColl).drop();
  }

  db.createCollection(tempColl, {timeseries: tsOptions});
  return tsOptions;
}

function shouldRetryTxnOnTransientError(e) {
  return e.hasOwnProperty('errorLabels') &&
         e.errorLabels.includes('TransientTransactionError');
}

//
// Helper to perform the actual re-insertion procedure for a single bucket.
//
function repairBucketByReinsertMeasurements(bucketId, srcColl, tsColl, tempColl, tsOptions) {
  const tempTimeseriesColl       = db.getCollection(tempColl);
  const tempTimeseriesBucketsColl = db.getCollection('system.buckets.' + tempColl);

  // Build the $_internalUnpackBucket spec.
  // bucketRoundingSeconds is NOT a valid parameter for $_internalUnpackBucket.
  const unpackSpec = {timeField: tsOptions.timeField};
  if (tsOptions.metaField) unpackSpec.metaField = tsOptions.metaField;
  if (tsOptions.bucketMaxSpanSeconds !== undefined)
    unpackSpec.bucketMaxSpanSeconds = NumberInt(tsOptions.bucketMaxSpanSeconds);

  // Unpack measurements from the regular source collection.
  const measurements = db.getCollection(srcColl)
      .aggregate(
          [{$match: {_id: bucketId}}, {$_internalUnpackBucket: unpackSpec}],
          {promoteValues: false})
      .toArray();

  if (measurements.length === 0) {
    print('Bucket ' + bucketId + ' not found or contains no measurements, skipping.');
    return;
  }

  // Insert measurements into the temporary timeseries collection in one batch.
  // Retry if any errors are encountered.
  let retryTempInsert;
  do {
    retryTempInsert = false;
    try {
      tempTimeseriesBucketsColl.deleteMany({});
      tempTimeseriesColl.insertMany(measurements);
    } catch (e) {
      print('An error occurred during internal insert, retrying. Error: ' + e);
      retryTempInsert = true;
    }
  } while (retryTempInsert);

  // Insert the repaired buckets into the target timeseries collection's bucket
  // store inside a transaction.  Retry on transient errors.
  let hasTransientError;
  do {
    hasTransientError = false;
    try {
      const session = db.getMongo().startSession({retryWrites: true});
      session.startTransaction();

      const sessionBucketColl = session.getDatabase(db.getName())
                                       .getCollection('system.buckets.' + tsColl);
      const bucketDocs = tempTimeseriesBucketsColl.find().toArray();
      sessionBucketColl.insertMany(bucketDocs);

      session.commitTransaction();
    } catch (e) {
      if (!shouldRetryTxnOnTransientError(e)) {
        throw e;
      }
      hasTransientError = true;
      print('Encountered a transient error. Retrying internal transaction.');
      continue;
    }
  } while (hasTransientError);

  print('Bucket ' + bucketId + ' repaired successfully.');
}

//
// Entry point for repairing one or many time-series bucket documents stored
// in a regular collection.
//
// Parameters
//   bucketId — ObjectId or array of ObjectId — the _id(s) of the bucket
//              documents in srcColl.
//   srcColl  — name of the regular collection containing the bucket documents.
//   tsColl   — name of the target timeseries collection (must already exist
//              with the correct timeField / metaField / bucket options).
//   tempColl — temporary timeseries collection used during repair. If it
//              exists its options must match tsColl; its data will be cleared.
//
function repairTimeseriesBucketViaRegularColl(bucketId, srcColl, tsColl, tempColl) {
  const tsOptions = verifyAndSetupCollsAndGetTSOptions(tsColl, tempColl);

  if (Array.isArray(bucketId)) {
    for (const bId of bucketId) {
      repairBucketByReinsertMeasurements(bId, srcColl, tsColl, tempColl, tsOptions);
    }
  } else {
    repairBucketByReinsertMeasurements(bucketId, srcColl, tsColl, tempColl, tsOptions);
  }

  db.getCollection(tempColl).drop();
  return true;
}
