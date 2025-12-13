/* eslint-env node, mongosh */
/* global db, print, quit, console, process, require, module */

// This is an async version of orphan_clean_script.js present in this directory
// modified by TSE team. This is the version that ran on customer cluster
// README on https://docs.google.com/document/d/1bz-mn1XdBgAbsCNP3i8wKCyGUi8gZpEBkjgxQ9PpE60/edit?tab=t.0

// Script to delete orphans whose ranges are defined in config.rangeDeletions
// on a shard mongod instance.
// batchStart = 0 refers to the first document in config.rangeDeletions
// batchEnd is exclusive, meaning it will process documents from batchStart to
// batchEnd - 1. To parallelize you can run multiple instances of this script
// working on different batch ranges.
//
// Add dry-run option to only print the ranges without deleting.

/**
 * Checks if the resumable range deleter is disabled and quits with instructions if it is.
 * Only checks the disableResumableRangeDeleter parameter if FCV >= 8.2,
 * since the parameter can only be set at runtime starting in 8.2.
 * @param {Object} dbObj - The database object (optional, defaults to global db)
 * @throws {Error} If FCV >= 8.2 and disableResumableRangeDeleter is enabled
 */
function checkResumableRangeDeleterDisabled(dbObj = null) {
    const database = dbObj || db;
    try {
        // Check FCV first - only check disableResumableRangeDeleter if FCV >= 8.2
        const fcvDoc = database.adminCommand({getParameter: 1, featureCompatibilityVersion: 1});
        if (fcvDoc.ok === 1 && fcvDoc.featureCompatibilityVersion) {
            const fcvVersion = fcvDoc.featureCompatibilityVersion.version;
            // Only check disableResumableRangeDeleter if FCV >= 8.2
            if (MongoRunner.compareBinVersions(fcvVersion, "8.2") >= 0) {
                const getParameterRes = database.adminCommand({getParameter: 1, disableResumableRangeDeleter: 1});
                if (getParameterRes.disableResumableRangeDeleter === false) {
                    const error = "Cannot run script while disableResumableRangeDeleter is disabled";
                    print(error);
                    print("To enable the resumable range deleter, run on the shard primary:");
                    print("  db.adminCommand({setParameter: 1, disableResumableRangeDeleter: true})");
                    if (typeof quit !== "undefined") {
                        quit(1);
                    }
                    throw new Error(error);
                }
            }
        }
        // If FCV < 8.2, parameter can't be set at runtime, so no check needed
    } catch (error) {
        // Re-throw if it's our error, otherwise handle gracefully
        if (error.message === "Cannot run script while disableResumableRangeDeleter is disabled") {
            throw error;
        }
        // If FCV check fails, assume not disabled (parameter may not exist in older versions)
    }
}

/**
 * Queries config.cache.collections to get the shard key pattern for a collection.
 * @param {string} nss - Namespace string (e.g., "db.collection")
 * @param {Object} dbObj - Database object (optional, defaults to global db)
 * @returns {Object} Shard key pattern object from config.cache.collections
 * @throws {Error} If the collection is not found in config.cache.collections
 */
function getShardKeyPatternFromCache(nss, dbObj = null) {
    const database = dbObj || db;
    const config = database.getSiblingDB("config");

    const collDoc = config.cache.collections.findOne({_id: nss});
    if (!collDoc) {
        throw new Error(
            `Collection ${nss} not found in config.cache.collections. ` +
                `Make sure you're connected to a shard and the collection is sharded.`,
        );
    }

    if (!collDoc.key) {
        throw new Error(`Shard key pattern not found for collection ${nss} in config.cache.collections`);
    }

    return collDoc.key;
}

/**
 * Checks if an index exists with an EXACT match to the shard key pattern on the target collection.
 * This is required because MongoDB's hint() with min/max requires an exact index match.
 * @param {string} nss - Namespace string (e.g., "db.collection")
 * @param {Object} shardKeyPattern - Shard key pattern object (e.g., {x: 1} or {x: "hashed"})
 * @param {Object} dbObj - Database object (optional, defaults to global db)
 * @returns {Object} The exact index key pattern from the matching index
 * @throws {Error} If no exact matching index is found for the shard key
 */
function checkShardKeyIndexExists(nss, shardKeyPattern, dbObj = null) {
    const database = dbObj || db;
    const [dbName, collName] = nss.split(".");
    const coll = database.getSiblingDB(dbName).getCollection(collName);

    // Check if any index EXACTLY matches the shard key (not just a prefix)
    const matchingIndex = coll.getIndexes().find((index) => {
        const shardKeyFields = Object.keys(shardKeyPattern);
        const indexKeyFields = Object.keys(index.key);

        // Must have the same number of fields (exact match, not prefix or extended)
        if (shardKeyFields.length !== indexKeyFields.length) {
            return false;
        }

        // All fields must match in order and type
        return shardKeyFields.every((field, i) => {
            const shardKeyType = shardKeyPattern[field];
            const indexKeyType = index.key[indexKeyFields[i]];
            return (
                field === indexKeyFields[i] &&
                (shardKeyType === "hashed"
                    ? indexKeyType === "hashed"
                    : shardKeyType !== "hashed" && indexKeyType !== "hashed")
            );
        });
    });

    if (!matchingIndex) {
        throw new Error(
            `No index found with exact match for shard key ${JSON.stringify(shardKeyPattern)} on collection ${nss}. ` +
                `The script requires an index that exactly matches the shard key pattern (not a prefix or extended index). ` +
                `Please create an index on the mongos: db.getSiblingDB("${dbName}").${collName}.createIndex(${JSON.stringify(shardKeyPattern)})`,
        );
    }

    return matchingIndex.key;
}

/**
 * Deletes documents using cursor iteration with min/max hints for compound hashed shard keys.
 * @param {Object} params - Parameters object
 * @param {string} params.targetNss - Target namespace
 * @param {Object} params.rangeQuery - Range query with min and max
 * @param {Object} params.keyPattern - Shard key pattern for the index hint
 * @param {number} params.numOrphanDocs - Expected number of orphan documents (for batch size optimization)
 * @param {boolean} params.isDryRun - Whether to run in dry-run mode
 * @param {Object} params.session - MongoDB session (optional, will create if not provided)
 * @param {Object} params.dbObj - Database object (optional, defaults to global db)
 * @returns {Promise<number>} Deleted count
 */
async function deleteWithCursorMin({
    targetNss,
    rangeQuery,
    keyPattern,
    numOrphanDocs,
    isDryRun = false,
    session = null,
    dbObj = null,
} = {}) {
    const database = dbObj || db;
    const sessionOpts = {};
    const mongoSession = session || database.getMongo().startSession(sessionOpts);

    const [dbName, collName] = targetNss.split(".");
    const namespace = mongoSession.getDatabase(dbName).getCollection(collName);

    // Adaptive cursor batch size: optimize network round trips based on expected document count
    const cursorBatchSize = Math.min(numOrphanDocs, 10000);
    const kDeleteBatchSize = 1000;

    if (isDryRun) {
        print(
            `Would delete documents in range: ${JSON.stringify(rangeQuery.min)} to ${JSON.stringify(rangeQuery.max)}`,
        );
        return 0;
    }

    // Validate that an exact matching index exists and get its key pattern
    // This ensures the hint will work correctly with min/max
    const validatedIndexKey = checkShardKeyIndexExists(targetNss, keyPattern, database);

    let deletedCount = 0;
    try {
        // Use cursor with min/max bounds for efficient range scanning
        // Only fetch _id field to minimize network bandwidth
        // Use the validated index key to ensure exact match for hint
        const cursor = namespace
            .find({}, {_id: 1})
            .min(rangeQuery.min)
            .max(rangeQuery.max)
            .hint(validatedIndexKey)
            .batchSize(cursorBatchSize);

        let docsToDelete = [];

        while (await cursor.hasNext()) {
            const doc = await cursor.next();
            docsToDelete.push(doc._id);

            // Delete in batches to avoid large $in arrays and provide incremental progress
            if (docsToDelete.length >= kDeleteBatchSize) {
                const deleteResult = await namespace.deleteMany(
                    {_id: {$in: docsToDelete}},
                    {writeConcern: {w: "majority"}},
                );
                deletedCount += deleteResult.deletedCount;
                print(`Deleted batch: ${deleteResult.deletedCount} documents (total: ${deletedCount})`);
                docsToDelete = [];
            }
        }

        if (docsToDelete.length > 0) {
            const deleteResult = await namespace.deleteMany(
                {_id: {$in: docsToDelete}},
                {writeConcern: {w: "majority"}},
            );
            deletedCount += deleteResult.deletedCount;
            print(`Deleted final batch: ${deleteResult.deletedCount} documents (total: ${deletedCount})`);
        }
    } catch (error) {
        print(`Error in deleteWithCursorMin: ${error}`);
    }

    return deletedCount;
}

/**
 * Deletes documents in a range for a single range deletion task.
 * @param {Object} params - Parameters object
 * @param {string} params.targetNss - Target namespace
 * @param {number} params.numOrphanDocs - Expected number of orphan documents
 * @param {Object} params.rangeQuery - Range query with min and max
 * @param {Object} params.keyPattern - Shard key pattern from range deletion document (optional)
 * @param {boolean} params.isDryRun - Whether to run in dry-run mode
 * @param {Object} params.session - MongoDB session (optional, will create if not provided)
 * @param {Object} params.dbObj - Database object (optional, defaults to global db)
 * @returns {Promise<Array<number>>} Array with deleted count [deletedCount]
 */
async function deleteManyTask({
    targetNss,
    numOrphanDocs,
    rangeQuery,
    keyPattern = null,
    isDryRun = false,
    session = null,
    dbObj = null,
} = {}) {
    const database = dbObj || db;
    const sessionOpts = {};
    const mongoSession = session || database.getMongo().startSession(sessionOpts);

    const [dbName, collName] = targetNss.split(".");

    // Use keyPattern from range deletion document if available, otherwise query config.cache.collections
    const shardKeyPattern = keyPattern || getShardKeyPatternFromCache(targetNss, database);

    const patternEntries = Object.entries(shardKeyPattern);

    // Check if any fields are hashed or all fields are hashed
    const hasHashedFields = patternEntries.some(([field, value]) => value === "hashed");
    const allFieldsHashed = patternEntries.every(([field, value]) => value === "hashed");

    let deleteQuery;
    let shardKeyObj;

    if (allFieldsHashed) {
        // Single-field hashed: use directly without $arrayToObject
        // (using $arrayToObject in $expr comparisons causes evaluation issues)
        // MongoDB only supports at most one hashed field, so patternEntries.length === 1
        const [field, value] = patternEntries[0];
        shardKeyObj = {$toHashedIndexKey: `$${field}`};
    } else if (hasHashedFields) {
        // Compound hashed {a: "hashed", b: 1} -> use cursor.min/max approach
        // This is more efficient than $expr with $arrayToObject for compound hashed keys
        print(`Processing range deletion task: ${JSON.stringify(rangeQuery)}`);
        print(`Expected orphan documents: ${numOrphanDocs}`);

        const deletedCount = await deleteWithCursorMin({
            targetNss,
            rangeQuery,
            keyPattern: shardKeyPattern,
            numOrphanDocs,
            isDryRun,
            session,
            dbObj,
        });

        return [deletedCount];
    } else {
        // Ranged or compound ranged - use regular field paths
        shardKeyObj = {};
        patternEntries.forEach(([field, value]) => {
            shardKeyObj[field] = `$${field}`;
        });
    }

    // For hashed keys, range boundaries are already hash values (NumberLong, MinKey, MaxKey).
    // We should NOT hash them again - just use the field value directly for comparison.
    let minValue = rangeQuery.min;
    let maxValue = rangeQuery.max;
    if (allFieldsHashed) {
        // Single-field hashed: use the boundary value directly (it's already a hash value)
        const [field] = patternEntries[0];
        minValue = rangeQuery.min[field];
        maxValue = rangeQuery.max[field];
    }

    deleteQuery = {
        $expr: {
            $and: [{$gte: [shardKeyObj, minValue]}, {$lt: [shardKeyObj, maxValue]}],
        },
    };

    print(`Processing range deletion task: ${JSON.stringify(rangeQuery)}`);
    print(`Expected orphan documents: ${numOrphanDocs}`);
    if (isDryRun) {
        print(`Delete query (dry-run): ${JSON.stringify(deleteQuery)}`);
        return [0];
    }

    const namespace = mongoSession.getDatabase(dbName).getCollection(collName);

    let deletedCount = 0;
    try {
        deletedCount = await namespace.deleteMany(deleteQuery, {
            writeConcern: {w: "majority"},
        }).deletedCount;
    } catch (error) {
        print(error);
    }

    return [deletedCount];
}

/**
 * Processes a batch of range deletion tasks.
 * @param {Object} params - Parameters object
 * @param {string} params.targetNss - Target namespace
 * @param {number} params.batchStart - Start index of batch
 * @param {number} params.batchEnd - End index of batch (exclusive)
 * @param {boolean} params.isDryRun - Whether to run in dry-run mode
 * @param {Object} params.configDB - Config database object (optional, defaults to dbObj.getSiblingDB("config"))
 * @param {Object} params.dbObj - Database object (optional, defaults to global db)
 * @returns {Promise<Object>} Object with totalDeletedDocs and processedTasks
 */
async function processRangeDeletionTasks({
    targetNss,
    batchStart,
    batchEnd,
    isDryRun = false,
    configDB = null,
    dbObj = null,
} = {}) {
    const database = dbObj || db;
    const config = configDB || database.getSiblingDB("config");

    // Get collection UUID from config.cache.collections to avoid matching tasks
    // from dropped collections that haven't been lazily removed yet
    let targetCollectionUuid = null;
    const collEntry = config.cache.collections.findOne({_id: targetNss});
    if (collEntry && collEntry.uuid) {
        targetCollectionUuid = collEntry.uuid;
    }

    const queryPredicate = {
        nss: targetNss,
        $or: [{pending: {$exists: false}}, {pending: false}],
    };

    // Include collectionUuid in predicate if available to avoid matching tasks
    // from dropped collections that haven't been lazily removed yet
    if (targetCollectionUuid) {
        queryPredicate.collectionUuid = targetCollectionUuid;
    }

    // Fetch the batch of range deletions within the specified range
    // Exclude pending tasks: filter out documents where pending field exists and is true
    // Order by range.min to ensure deterministic ordering when multiple tasks exist
    // This ensures tasks are processed in a consistent order based on their range min value
    const rangeDeletionsCursor = config.rangeDeletions
        .find(queryPredicate)
        .sort({"range.min": 1})
        .skip(batchStart)
        .limit(batchEnd - batchStart);

    // Fetch an array of range deletion tasks
    const rangeDeletions = await rangeDeletionsCursor.toArray();

    let totalDeletedDocs = 0;
    let processedTasks = 0;

    // Map each range deletion task to an async deletion operation
    const deletionTasks = rangeDeletions.map((range, index) => {
        return deleteManyTask({
            targetNss: targetNss,
            numOrphanDocs: range.numOrphanDocs,
            rangeQuery: range.range,
            keyPattern: range.keyPattern,
            isDryRun: isDryRun,
            dbObj: database,
        });
    });

    // Wait for all deletion tasks to complete in parallel
    const results = await Promise.all(deletionTasks);

    // Process results
    results.forEach((result, index) => {
        processedTasks++;
        const deletedCount = result[0]; // returned as [deletedCount]
        if (!isDryRun) {
            totalDeletedDocs += deletedCount;
            print(`Task ${index + 1}: Deleted ${deletedCount} documents.`);
        }
    });

    return {totalDeletedDocs, processedTasks};
}

/**
 * Main function to run the script with command-line arguments.
 * @param {Array<string>} args - Command-line arguments (optional, defaults to process.argv.slice(2))
 * @param {Object} dbObj - Database object (optional, defaults to global db). Should be a connection to the shard where orphans exist.
 * @param {Object} options - Options object
 * @param {boolean} options.throwOnError - If true, throw errors instead of calling quit(). Used for testing.
 * @returns {Promise<Object>} Result object with totalDeletedDocs and processedTasks
 */
export async function runScript(args = null, dbObj = null, options = {}) {
    const database = dbObj || db;
    const scriptArgs = args || process.argv.slice(2);
    const {throwOnError = false} = options;

    // Script to delete orphans whose ranges are defined in
    // config.rangeDeletions. batchStart = 0 refers to the first document in
    // config.rangeDeletions batchEnd is exclusive, meaning it will process
    // documents from batchStart to batchEnd - 1
    // Expected args: [nss, batchStart, batchEnd, ...dry-run?]
    if (scriptArgs.length < 3 || scriptArgs.length > 4) {
        const usage =
            "Usage: mongosh <connection_string> --file <script.js> <dbName.collectionName> <batchStart> <batchEnd> [dry-run]";
        print(usage);
        if (!throwOnError && typeof quit !== "undefined") {
            quit(1);
        }
        throw new Error(usage);
    }

    const targetNss = scriptArgs[0]; // nss we want to delete orphans from
    const batchStart = parseInt(scriptArgs[1]); // Start index of the batch of range deletion tasks
    const batchEnd = parseInt(scriptArgs[2]); // End index of the batch of range deletion tasks
    const isDryRun = scriptArgs.includes("dry-run"); // Check for the dry-run flag

    if (isNaN(batchStart) || isNaN(batchEnd) || batchStart < 0 || batchEnd <= batchStart) {
        const error = "Error: Invalid batch range. Ensure batchStart >= 0 and batchEnd > batchStart.";
        print(error);
        if (!throwOnError && typeof quit !== "undefined") {
            quit(1);
        }
        throw new Error(error);
    }

    print("---------------------------");
    print("Orphan Documents Cleanup Script");
    print("---------------------------");
    print(`Target Namespace: ${targetNss}`);
    print(`Processing batch range: ${batchStart} to ${batchEnd} (excluded)`);

    if (isDryRun) {
        print("*** Running in Dry-Run Mode (No documents will be deleted) ***");
    } else {
        print("*** Running in Live Mode (Documents will be deleted) ***");
    }

    // Verify shard key can be retrieved from config.cache.collections
    // and that an index exists for the shard key before running the script.
    try {
        const shardKeyPattern = getShardKeyPatternFromCache(targetNss, database);
        checkShardKeyIndexExists(targetNss, shardKeyPattern, database);
        print(`Shard key pattern: ${JSON.stringify(shardKeyPattern)}`);
        print(`Verified index exists for shard key`);
    } catch (error) {
        print(`Error: ${error.message}`);
        if (!throwOnError && typeof quit !== "undefined") {
            quit(1);
        }
        throw error;
    }

    checkResumableRangeDeleterDisabled(database);

    const result = await processRangeDeletionTasks({
        targetNss: targetNss,
        batchStart: batchStart,
        batchEnd: batchEnd,
        isDryRun: isDryRun,
        dbObj: database,
    });

    print("---------------------------");
    print(`Script Execution Completed.`);
    print(`Total range deletion tasks processed: ${result.processedTasks}`);
    if (isDryRun) {
        print(`Dry-run complete. No documents were deleted.`);
    } else {
        print(`Total documents deleted: ${result.totalDeletedDocs}`);
    }
    print("---------------------------");

    return result;
}

// CLI entry point - only run if executed directly (not imported)
// Check if we're running as a script (not being imported/loaded for testing)
const isDirectExecution =
    (typeof require !== "undefined" && require.main === module) ||
    (typeof process !== "undefined" && process.argv && process.argv.length > 2);

if (isDirectExecution) {
    (async () => {
        try {
            // For mongosh --file script.js arg1 arg2 arg3, process.argv is:
            // [node_path, mongosh_path, '--file', 'script.js', 'arg1', 'arg2', 'arg3']
            // So we need to skip the first 4 elements to get the actual args
            const adjustedArgs = process.argv.slice(2);
            // Check if we're running via mongosh --file (has --file flag)
            const fileIndex = adjustedArgs.indexOf("--file");
            if (fileIndex >= 0 && fileIndex + 1 < adjustedArgs.length) {
                // Skip --file and script filename, take the rest
                const actualArgs = adjustedArgs.slice(fileIndex + 2);
                await runScript(actualArgs);
            } else {
                // Direct execution, use args as-is
                await runScript(adjustedArgs);
            }
        } catch (error) {
            console.error(error);
            if (typeof quit !== "undefined") {
                quit(1);
            }
            if (typeof process !== "undefined" && process.exit) {
                process.exit(1);
            }
        }
    })();
}
