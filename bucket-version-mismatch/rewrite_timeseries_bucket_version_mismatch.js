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
// We can't pattern match with the entire v2 error message because we include
// the fieldName of the unsorted v2 bucket.
const v2ErrorMsg = 'field is not in ascending order';
const v3ErrorMsg =
    'Time-series bucket is v3 but has its measurements in-order on time';

const BucketVersion = {
  kCompressedSorted: 2,
  kCompressedUnsorted: 3
};

const GetLogResult = Object.freeze({
  successTrue: 'successTrue',
  successFalse: 'successFalse',
  fail: 'fail',
});

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
  const bucketsColl = db.getCollection('system.buckets.' + coll.getName());
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

function checkValidateResForBucketVersionMismatch(validateRes) {
  return (validateRes.errors.length != 0 &&
          validateRes.errors.some(x => x.includes('6698300'))) ||
      (validateRes.warnings.length != 0 &&
       validateRes.warnings.some(x => x.includes('6698300')));
}

function checkLogsForBucketVersionMismatch() {
  const getLogRes = db.adminCommand({getLog: 'global'});
  if (getLogRes.ok) {
    return (getLogRes.log
                .filter(
                    line =>
                        (line.includes('6698300') &&
                         (line.includes(v2ErrorMsg) ||
                          line.includes(v3ErrorMsg))))
                .length > 0) ?
        GetLogResult.successTrue :
        GetLogResult.successFalse;
  }
  return GetLogResult.fail;
}

//
// Steps 1 & 2: Detect if the bucket has bucket version mismatch and change
// the buckets with bucket version mismatch to the correct version.
//
runFixBucketVersionMismatchProcedure(collName);

//
// Step 3: Validate that there are no bucket version mismatches.
//
print('Validating that there are no mismatched bucket versions ...\n');
db.getMongo().setReadPref('secondaryPreferred');
const validateRes = collName.validate({background: true});

//
// For v8.1.0+, buckets that have a bucket version mismatch will lead to a
// error during validation.
//
// Prior to v8.1.0, buckets that have a bucket version mismatch will lead to a
// warning during validation.
//
const validateResCheck = checkValidateResForBucketVersionMismatch(validateRes);
const logsCheck = checkLogsForBucketVersionMismatch();

if (validateResCheck && logsCheck == GetLogResult.successTrue) {
  print(
      '\nThere is still a time-series bucket(s) that has a bucket version mismatch. Check logs with id 6698300.');
  exit(1);
} else if (validateResCheck && logsCheck == GetLogResult.successFalse) {
  print(
      '\nScript successfully fixed mismatched bucket versions. There is another error or warning during validation. Check mongodb logs for more details.');
  exit(0);
} else if (validateResCheck && logsCheck == GetLogResult.fail) {
  print(
      '\nWe detected a validation error with log id 6698300 and getLog() failed. We cannot programmatically determine if the issue was remediated.');
  print(
      '\nCheck that there aren\'t logs with id 6698300 and the error messages\n' +
      v2ErrorMsg + ' or \n' + v3ErrorMsg +
      '\nto ensure the remediation was successful.');
  exit(0);
}

print('\nScript successfully fixed mismatched bucket versions!');
exit(0);
