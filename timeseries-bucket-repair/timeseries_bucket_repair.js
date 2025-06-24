// ------------------------------------------------------------------------------------
// This script provides functionality to unconditionally re-write an internal
// time-series bucket. It can be used for most types of logical bucket
// corruption detected by validate.
// ------------------------------------------------------------------------------------

//
// Helper function to validate namespaces, create temporary collection and
// return our timeseries options.
//
function verifyAndSetupCollsAndGetTSOptions(collName, tempColl) {
  tsOptions = db.runCommand({listCollections : 1.0, filter : {name : collName}})
                  .cursor.firstBatch[0]
                  .options.timeseries;

  if (tsOptions === undefined) {
    throw ('Collection "' + collName + '" is not a timeseries collection.');
  }

  // Verify that the temp collection has the same options if it exists
  tempRes = db.runCommand({listCollections : 1.0, filter : {name : tempColl}})
                .cursor.firstBatch;
  if (tempRes && tempRes.length > 0) {
    tempOptions = tempRes[0].options.timeseries;
    if (tempOptions === undefined ||
        tsOptions.timeField != tempOptions.timeField ||
        tsOptions.metaField != tempOptions.metaField ||
        tsOptions.granularity != tempOptions.granularity ||
        tsOptions.bucketMaxSpanSeconds != tempOptions.bucketMaxSpanSeconds) {
      throw (
          'Temp collection "' + tempColl +
          '" exists but contain unexpected options. Please specify a different temporary namespace.');
    }
    db.getCollection(tempColl).drop();
  }

  db.createCollection(tempColl, {timeseries : tsOptions});
  return tsOptions;
}

//
// Helper to perform the actual re-insertion procedure.
//
function repairBucketByReinsertMeasurements(bucketId, collName, tempColl,
                                            tsOptions) {
  // Fetch collections that we need
  bucketColl = db.getCollection('system.buckets.' + collName);
  tempTimeseriesColl = db.getCollection(tempColl);
  tempTimeseriesBucketsColl = db.getCollection('system.buckets.' + tempColl);

  // Prevent concurrent changes on this bucket by setting control.closed.
  updateRes = bucketColl.updateOne({_id : bucketId},
                                   {$set : {'control.closed' : true}});
  if (updateRes.matchedCount == 1) {
    print('Bucket ' + bucketId + ' not found, aborting.');
    return;
  }

  // Get the measurements from the bucket that we want to repair
  let measurements;
  if (tsOptions.metaField) {
    measurements = bucketColl
                       .aggregate(
                           [
                             {$match : {_id : bucketId}}, {
                               $_unpackBucket : {
                                 timeField : tsOptions.timeField,
                                 metaField : tsOptions.metaField,
                               }
                             }
                           ],
                           {promoteValues : false})
                       .toArray();
  } else {
    measurements = bucketColl
                       .aggregate(
                           [
                             {$match : {_id : bucketId}}, {
                               $_unpackBucket : {
                                 timeField : tsOptions.timeField,
                               }
                             }
                           ],
                           {promoteValues : false})
                       .toArray();
  }

  if (measurements.length == 0) {
    print('Bucket ' + bucketId + ' not found, skipping.');
    return;
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
      print('An error occurred during internal insert, retrying. Error: ' + e);
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
      const session = db.getMongo().startSession({retryWrites : true});
      session.startTransaction();

      const sessionBucketColl =
          session.getDatabase(db.getName())
              .getCollection('system.buckets.' + collName);
      sessionBucketColl.deleteOne({_id : bucketId});
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
}

//
// Entry point for repairing one or many time-series buckets.
//
// bucketId: Internal bucket _id of type ObjectId or an array of ObjectId
// collName: String of the time-series namespace to repair
// tempColl: String of a temporary namespace to use during the repair. This
// should be an unused namespace, if it exists its data will be lost.
//
function repairTimeseriesBucket(bucketId, collName, tempColl) {
  tsOptions = verifyAndSetupCollsAndGetTSOptions(collName, tempColl);

  if (Array.isArray(bucketId)) {
    for (const bId of bucketId) {
      repairBucketByReinsertMeasurements(bId, collName, tempColl, tsOptions);
    }
  } else {
    repairBucketByReinsertMeasurements(bucketId, collName, tempColl, tsOptions);
  }

  db.getCollection(tempColl).drop();

  return true;
}
