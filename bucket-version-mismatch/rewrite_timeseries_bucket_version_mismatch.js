// ------------------------------------------------------------------------------------
// Populate collName with the time-series collection that failed validation due
// to v2/v3 timeseries buckets not in correct sorted/unsorted order
// respectively.
// ------------------------------------------------------------------------------------
const collName = 'your_collection_name';

let listCollectionsRes = db.runCommand({
                             listCollections: 1.0,
                             filter: {name: collName}
                           }).cursor.firstBatch;
if (listCollectionsRes.length == 0) {
  print(
      'Collection not found. Populate collName with the time-series collection that failed due to v2/v3 timeseries buckets not in correct sorted/unsorted order respectively.');
  exit(1);
}
const coll = db.getCollection(collName);

//
// NON-MODIFIABLE CODE BELOW
//
// ---------------------------------------------------------------------------------------
// The script will, for each bucket in the affected time-series collection:
// 1) Detect if the bucket has bucket version mismatch.
// 2) Change the buckets with bucket version mismatch to the correct version.
// 3) Validate that there are no bucket version mismatches.
// ----------------------------------------------------------------------------------------

BucketVersion = {
  kCompressedSorted: 2,
  kCompressedUnsorted: 3
};

function bucketHasMismatchedBucketVersion(
    bucketsColl, bucketId, bucketControlVersion) {
  let measurements = bucketsColl
                         .aggregate([
                           {$match: {_id: bucketId}}, {
                             $_unpackBucket: {
                               timeField: 't',
                             }
                           }
                         ])
                         .toArray();
  let prevTimestamp = new Date(-8640000000000000);
  let detectedOutOfOrder = false;
  for (let i = 0; i < measurements.length; i++) {
    let currMeasurement = measurements[i]['t'];
    let currTimestamp = new Date(currMeasurement);
    if (currTimestamp < prevTimestamp) {
      if (bucketControlVersion == BucketVersion.kCompressedSorted) {
        return true;
      } else if (bucketControlVersion == BucketVersion.kCompressedUnsorted) {
        detectedOutOfOrder = true;
      }
    }
    prevTimestamp = currTimestamp;
  }
  return !detectedOutOfOrder &&
      (bucketControlVersion == BucketVersion.kCompressedUnsorted);
}

function runFixBucketVersionMismatchProcedure(collName) {
  print(
      'Checking if the bucket versions match their data in ' + collName +
      ' ...\n');
  // Range through all the bucketDocs and change the control version of the
  // bucket from 2 -> 3 if the data is not sorted or from 3 -> 2 if the data is
  // sorted.
  const bucketsColl = db.getCollection('system.buckets.' + collName);
  var cursor = bucketsColl.find({});

  while (cursor.hasNext()) {
    const bucket = cursor.next();
    const bucketId = bucket._id;
    const bucketControlVersion = bucket.control.version;
    if (bucketHasMismatchedBucketVersion(
            bucketsColl, bucketId, bucketControlVersion)) {
      if (bucketControlVersion == BucketVersion.kCompressedSorted) {
        assert.commandWorked(bucketsColl.updateOne(
            {_id: bucketId},
            {$set: {'control.version': BucketVersion.kCompressedUnsorted}}));
      } else if (bucketControlVersion == BucketVersion.kCompressedUnsorted) {
        assert.commandWorked(bucketsColl.updateOne(
            {_id: bucketId},
            {$set: {'control.version': BucketVersion.kCompressedSorted}}));
      }
    }
  }
}

//
// Steps 1 & 2: Fix the bucket version by updating unsorted v2 buckets to v3
// buckets and sorted v3 buckets to v2 buckets.
//
runFixBucketVersionMismatchProcedure(collName);

//
// Step 3: Validate that there are no more mismatched bucket versions
//
print('Validating that there are no mismatched bucket versions ...\n');
db.getMongo().setReadPref('secondaryPreferred');
const validateRes = collName.validate({full: true});
if (validateRes.errors.length != 0) {
  print(
      '\nThere is still a time-series bucket with a bucket version mismatch, or there is another error during validation.');
  exit(1);
}

print('\nScript successfully fixed mismatched bucket versions!');
exit(0);
