// timeseries-restore-via-regular-coll.js
//
// Restores a timeseries collection whose bucket documents were previously
// dumped into a regular collection (srcBucketsColl).
//
// Load this script in mongosh with load(), then call runCopyWithRepair()
// with your configuration parameters.
//
// High-level per bucket (from regular srcBucketsColl):
//   1) Try insert bucket into system.buckets.<tsColl>.
//      - If OK: strictly valid, copied; we then delete from srcBucketsColl.
//      - If DuplicateKey: already copied in an earlier run; treat as success,
//        delete from source.
//      - Otherwise: go to repair.
//   2) Repair path:
//      - Use $_internalUnpackBucket + $out to write the bucket's measurements
//        into a temporary time-series collection (tmpRepairTsColl) with the
//        same timeseries options.
//      - Transactionally insert the repaired buckets from system.buckets.<tmpRepairTsColl>
//        into system.buckets.<tsColl> AND delete the source doc from srcBucketsColl.
//      - If the transaction fails: mark the *original* bucket in badBucketsColl
//        and then delete it from srcBucketsColl.
//   3) Resume behavior:
//      - Any bucket still present in srcBucketsColl is "not fully processed".
//      - Direct-insert path is idempotent: DuplicateKey on resume → treated as success.
//      - Repair path is idempotent: the repaired-insert + source-delete happen in a
//        single transaction, so a crash leaves the source doc in place and the next
//        run re-runs $out cleanly (no duplicate measurements).
//      - Bad-bucket path is idempotent: bad uses replaceOne+upsert.

// ---------------------------------------------------------------------------
// HELPERS
// ---------------------------------------------------------------------------

function makeUnpackSpec(tsOptions) {
    const spec = {timeField: tsOptions.timeField};
    if (tsOptions.metaField) spec.metaField = tsOptions.metaField;
    if (tsOptions.bucketMaxSpanSeconds !== undefined)
        spec.bucketMaxSpanSeconds = NumberInt(tsOptions.bucketMaxSpanSeconds);
    // bucketRoundingSeconds is NOT a valid parameter for $_internalUnpackBucket;
    // it belongs only in the $out.timeseries spec (see makeTimeseriesOutSpec).
    return spec;
}

function makeTimeseriesOutSpec(tsOptions) {
    const spec = {timeField: tsOptions.timeField};
    if (tsOptions.metaField) spec.metaField = tsOptions.metaField;
    if (tsOptions.bucketMaxSpanSeconds !== undefined)
        spec.bucketMaxSpanSeconds = NumberInt(tsOptions.bucketMaxSpanSeconds);
    if (tsOptions.bucketRoundingSeconds !== undefined)
        spec.bucketRoundingSeconds = NumberInt(tsOptions.bucketRoundingSeconds);
    return spec;
}

// ---------------------------------------------------------------------------
// REPAIR LOGIC FOR A SINGLE BUCKET
// ---------------------------------------------------------------------------

// tsColl is the name (string) of the target timeseries collection, not a collection handle.
function tryRepairBucket(bucket, dbObj, srcBucketsColl, tmpRepairTsColl, tsColl, tsOptions) {
    const dbName   = dbObj.getName();
    const bucketId = bucket._id;

    print(`Attempting repair of bucket _id=${bucketId} via $_internalUnpackBucket + $out ...`);

    // Drop the temp collection before each repair so we never read stale data
    // left behind when $out receives 0 documents (it may not clear the collection
    // in that case).
    dbObj.getCollection(tmpRepairTsColl).drop();

    const pipeline = [
        {$match: {_id: bucketId}},
        {$_internalUnpackBucket: makeUnpackSpec(tsOptions)},
        {
            $out: {
                db: dbName,
                coll: tmpRepairTsColl,
                timeseries: makeTimeseriesOutSpec(tsOptions),
            },
        },
    ];

    const aggCmd = {
        aggregate: srcBucketsColl,
        pipeline:  pipeline,
        cursor:    {},
        allowDiskUse:   true,
        writeConcern:   {w: "majority"},
    };

    let aggRes;
    try {
        aggRes = dbObj.runCommand(aggCmd);
    } catch (e) {
        print(`  Repair aggregation threw for bucket _id=${bucketId}: ${e}`);
        return {ok: false, error: e};
    }

    if (!aggRes.ok) {
        print(`  Repair aggregation failed for bucket _id=${bucketId}: ${JSON.stringify(aggRes)}`);
        return {ok: false, error: aggRes};
    }

    const repairedBuckets = dbObj.getCollection("system.buckets." + tmpRepairTsColl).find().toArray();

    if (!repairedBuckets.length) {
        print(`  Repair produced no measurements for bucket _id=${bucketId}.`);
        return {ok: false, error: "noMeasurements"};
    }

    // Atomically insert repaired buckets into the destination AND delete the source doc
    // in a single transaction.  This is required for resumability: $out generates
    // non-deterministic bucket _ids on each run, so a crash after some repaired inserts
    // but before src.deleteOne would cause a second run to insert a second set of buckets
    // (with different _ids) and duplicate measurements.  With a transaction, either both
    // the inserts and the delete commit together, or neither does — the source doc
    // survives any abort and the next run starts clean.
    let hasTransientError;
    do {
        hasTransientError = false;
        const session = dbObj.getMongo().startSession({retryWrites: true});
        try {
            session.startTransaction({writeConcern: {w: "majority"}});
            session.getDatabase(dbName).getCollection("system.buckets." + tsColl)
                   .insertMany(repairedBuckets);
            session.getDatabase(dbName).getCollection(srcBucketsColl)
                   .deleteOne({_id: bucketId});

            while (true) {
                try {
                    session.commitTransaction();
                    break;
                } catch (commitErr) {
                    if (commitErr.hasOwnProperty('errorLabels') &&
                        commitErr.errorLabels.includes('UnknownTransactionCommitResult')) {
                        print('Encountered an unknown commit result. Retrying commit.');
                        continue;
                    }
                    throw commitErr;
                }
            }
        } catch (e) {
            try { session.abortTransaction(); } catch (_) {}
            if (e.hasOwnProperty('errorLabels') && e.errorLabels.includes('TransientTransactionError')) {
                hasTransientError = true;
                print('Encountered a transient error. Retrying repair transaction.');
                continue;
            }
            print(`  Repair transaction failed for bucket _id=${bucketId}: ${e}`);
            return {ok: false, error: e};
        } finally {
            try { session.endSession(); } catch (_) {}
        }
    } while (hasTransientError);

    print(`  Repair succeeded for bucket _id=${bucketId}.`);
    return {ok: true};
}

// ---------------------------------------------------------------------------
// MAIN FUNCTION
// ---------------------------------------------------------------------------
//
// Parameters
//   dbObj           — Db handle, e.g. db.getSiblingDB("mydb")
//   srcBucketsColl  — name of the regular collection holding the bucket dumps
//   tsColl          — name of the target timeseries collection (must already exist)
//   tmpRepairTsColl — name of the temporary TS collection used during repair
//   badBucketsColl  — name of the collection where unrepaired buckets are stored
//   batchSize       — cursor batch size (default 1000); tune for memory/throughput
//
// Returns {totalProcessed, totalRepaired, totalBad}.

function runCopyWithRepair(dbObj, srcBucketsColl, tsColl, tmpRepairTsColl, badBucketsColl, batchSize) {
    batchSize = (batchSize !== undefined) ? batchSize : 1000;
    const dbName = dbObj.getName();

    // Safety: ensure namespaces are distinct and callers pass logical collection names.
    const names = [srcBucketsColl, tsColl, tmpRepairTsColl, badBucketsColl];
    if (new Set(names).size !== names.length) {
        throw new Error(`Collection names must be distinct. Got: ${names.join(", ")}`);
    }
    for (const n of names) {
        if (typeof n !== "string" || n.length === 0) {
            throw new Error(`Collection name must be a non-empty string. Got: ${JSON.stringify(n)}`);
        }
        if (n.startsWith("system.buckets.")) {
            throw new Error("Pass logical collection names only (do not include the 'system.buckets.' prefix).");
        }
    }
    // Validate that the target collection exists and is a timeseries collection,
    // and fetch its options for use in the unpack/out specs.
    const tsInfoArr = dbObj.getCollectionInfos({name: tsColl});
    if (tsInfoArr.length === 0) {
        throw new Error(`Timeseries collection '${tsColl}' does not exist in db '${dbName}'.`);
    }
    const tsOptions = tsInfoArr[0].options && tsInfoArr[0].options.timeseries;
    if (!tsOptions) {
        throw new Error(`Collection '${tsColl}' is not a timeseries collection (no timeseries options).`);
    }

    const src         = dbObj.getCollection(srcBucketsColl);
    const bad         = dbObj.getCollection(badBucketsColl);
    const destBuckets = dbObj.getCollection("system.buckets." + tsColl);

    let totalProcessed = 0;
    let totalRepaired  = 0;
    let totalBad       = 0;

    print(`Starting copy from '${dbName}.${srcBucketsColl}' ` +
          `to '${dbName}.system.buckets.${tsColl}' ...`);

    while (true) {
        // Re-open the cursor each outer iteration so a cursor timeout in the
        // inner loop does not silently skip unprocessed documents.
        const cursor = src.find().sort({_id: 1}).batchSize(batchSize);
        if (!cursor.hasNext()) {
            break;
        }

        while (cursor.hasNext()) {
            const bucket   = cursor.next();
            const bucketId = bucket._id;
            totalProcessed++;

            let ok = false;

            // 1) Direct insert — succeeds for strictly valid buckets.
            try {
                destBuckets.insertOne(bucket);
                ok = true;
            } catch (e) {
                if (e.code === 11000) {
                    // Already present from a previous run; treat as success.
                    ok = true;
                } else {
                    print(`Direct insert FAILED for bucket _id=${bucketId}: ` +
                          `code=${e.code}, msg=${e.errmsg || e.message}`);
                }
            }

            // 2) Repair path for buckets that fail direct insertion.
            //    On success, tryRepairBucket deletes the source doc inside its transaction,
            //    so we must not delete it again in step 3.
            let srcDeletedByRepair = false;
            if (!ok) {
                const repairRes = tryRepairBucket(
                    bucket, dbObj, srcBucketsColl, tmpRepairTsColl, tsColl, tsOptions
                );
                if (repairRes.ok) {
                    ok = true;
                    totalRepaired++;
                    srcDeletedByRepair = true;
                } else {
                    totalBad++;
                    print(`  Repair also FAILED for bucket _id=${bucketId}, recording as bad.`);

                    // Serialize JS Error objects explicitly — their properties are non-enumerable
                    // and would be lost in BSON serialization as {}.
                    // Use replaceOne+upsert so re-runs overwrite the error from prior runs.
                    const errorDoc = (repairRes.error instanceof Error)
                        ? {message: repairRes.error.message, code: repairRes.error.code}
                        : repairRes.error;
                    bad.replaceOne(
                        {_id: bucketId},
                        {_id: bucketId, originalBucket: bucket, error: errorDoc},
                        {upsert: true}
                    );
                }
            }

            // 3) Delete source doc only after dest/bad write is confirmed.
            //    Crash before this point → source doc survives → safe re-process on next run.
            //    Skip if repair already deleted it atomically inside its transaction.
            if (!srcDeletedByRepair) {
                const delRes = src.deleteOne({_id: bucketId});
                if (delRes.deletedCount !== 1) {
                    throw new Error(
                        `Invariant violation: expected to delete 1 doc with _id=${bucketId} from ` +
                        `${dbName}.${srcBucketsColl}, got ${delRes.deletedCount}`
                    );
                }
            }
        }
        // Loop back to get a fresh cursor over what remains (if anything).
    }

    print(`Copy + validation + repair phase complete.`);
    print(`  Total processed buckets: ${totalProcessed}`);
    print(`  Total repaired buckets:  ${totalRepaired}`);
    print(`  Total unrepaired (bad):  ${totalBad}`);
    print(`Corrupted/unrepaired buckets are stored in '${dbName}.${badBucketsColl}'.`);

    return {totalProcessed, totalRepaired, totalBad};
}

