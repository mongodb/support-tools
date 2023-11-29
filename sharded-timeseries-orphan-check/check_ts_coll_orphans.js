//
// USAGE:
//
// 1. Connect to a mongos process
//
// 2. Invoke checkTimeseriesOrphansOnCluster()
//
//    - By default, the function will print out an [ERROR] message for each shard+timeseries 
//      combination containing one or more orphaned documents.
//
//    - A full report can be produced by passing in a namespace value (in "dbName.collName" format)
//      as an optional argument. 
//      The report will be represented by a collection containing one document for each orphan detected, 
//      according to the following schema:
//      {
//        _id: for internal use; THIS FIELD HAS TO BE IGNORED!!
//        orphanDocData: {
//          _id: the identifier of the orphan document within its parent (buckets) collection.
//          parentNamespace: the namespace of the (buckets) collection containing the orphaned doc.
//          foundIn: the shard ID where the orphaned doc has been retrieved.
//        }
//      }
//


//
// USER-MODIFIABLE PARAMETERS
//

// TODO review comment below.
// The script will establish a series of direct connection to shards, 
// for which extra user credentials might need to be specified.
// In order to do this, you can replace the value of the credentialsForDirectConnection parameter 
// using the following template:
// 
// const credentialsForDirectConnection = {
//     username: <the username required to establish a direct connection to a shard>,
//     password: <the related password>,
//     authSource: <the name of the collection containing set of user credentials>
//     tls: <Specifies whether to connect using tls - this is required for Atlas clusters>
// };
const credentialsForDirectConnection = {};

// By default, the script applies a strict check of collection data and internal metadata by performing 
// consistent reads (readConcern.level = 'snapshot'). 
// Such a configuration guarantees accurate results, although the script may occasionally fail due "SnapshotTooOld" errors 
// when the cluster in under heavy user write load.
//
// Alternatively, the check can be performed in 'non-strict mode' (using majority read concern level), 
// which allows to avoid the aforementioned failure. 
// NOTE: Non-strict mode may detect false orphans in case a range deletion task is completed during the check.
let performStrictCheck = true;

//
// NON-MODIFIABLE CODE BELOW
//
const configDB = db.getSiblingDB("config");

function getConnectionsToShards() {
    let conns = {};
    const authDb = credentialsForDirectConnection
        ? credentialsForDirectConnection.authSource
        : "admin";
    const loginPrefix = credentialsForDirectConnection
        ? `${credentialsForDirectConnection.username}:${credentialsForDirectConnection.password}@`
        : '';
    const tlsSetting = credentialsForDirectConnection.tls ? `${credentialsForDirectConnection.tls}` : 'false';

    configDB.shards.find().forEach(shardDoc => {
        const rsSeparatorIdx = shardDoc.host.indexOf('/');
        const firstNodeSeparatorIdx = shardDoc.host.indexOf(',');
        const rsName = shardDoc.host.substring(0, rsSeparatorIdx);
        const rsNodeHost = (firstNodeSeparatorIdx < 0)
            ? shardDoc.host.substring(rsSeparatorIdx + 1)
            : shardDoc.host.substring(rsSeparatorIdx + 1, firstNodeSeparatorIdx);
        print(`Attempting to open connection to: ${shardDoc._id}`);
        const connString =
            `mongodb://${loginPrefix}${rsNodeHost}/?replicaSet=${rsName}&authSource=${authDb}&tls=${tlsSetting}`;
        conns[shardDoc._id] = new Mongo(connString);
    });
    return conns;
};

//  Returns an array containing the _id of each orphan document of timeseriesCollDoc detected on
//  shardId.
function getOrphansForTimeseriesCollectionOnShard(timeseriesCollDoc, shardId, shardConn) {
    let orphanDocumentIds = [];

    const now = shardConn.getDB('admin').runCommand({ isMaster: 1 }).operationTime;

    // Retrieve the list of collection chunk boundaries not owned by the targeted shard.
    let notOwnedChunks = [];
    configDB.chunks.find({ uuid: timeseriesCollDoc.uuid, shard: { $ne: shardId } })
        .forEach(chunkDoc => {
            const min = Object.values(Object.assign({}, chunkDoc.min));
            const max = Object.values(Object.assign({}, chunkDoc.max));
            notOwnedChunks.push({ min: min, max: max });
        });

    if (notOwnedChunks.length === 0) {
        // There are no chunks living outside of this shard for the targeted TS collection; return
        // an empty result.
        return orphanDocumentIds;
    }

    // Expressions supporting findNotOwnedDocsPipeline.
    const shardKeyPattern = Object.assign({}, timeseriesCollDoc.key);
    let maxShardKeyValue = {}
    Object.entries(shardKeyPattern).forEach(([key, value]) => { maxShardKeyValue[key] = MaxKey() });

    const skValueExpr = Object.entries(shardKeyPattern).map(([key, value]) => {
        if (value === "hashed") {
            return { $toHashedIndexKey: `$${key}` };
        }

        return { $ifNull: [`$${key}`, null] };
    });

    function getProjectionStage() {
        let stage = { $project: { _id: 1, shardKeyValue: {} } };
        Object.entries(shardKeyPattern).forEach(([key, value]) => {
            if (value === "hashed") {
                stage['$project']['shardKeyValue'][key] = { $toHashedIndexKey: `$${key}` };
            } else {
                stage['$project']['shardKeyValue'][key] = `$${key}`;
            }
        });
        return stage;
    };

    // Aggregation that retrieves _id and shard key value of each document not owned by the shard.
    const findNotOwnedDocsPipeline = [{
        $match: {
            $expr: {
                $let: {
                    vars: { sk: skValueExpr },
                    in: {
                        // Does the current document fall within the boundaries of a not-owned chunk?
                        $anyElementTrue: [
                            {
                                $map: {
                                    input: notOwnedChunks,
                                    as: "chunkDoc",
                                    in: {
                                        $and: [
                                            { $gte: ["$$sk", "$$chunkDoc.min"] },
                                            {
                                                $or: [
                                                    { $lt: ['$$sk', "$$chunkDoc.max"] },
                                                    {
                                                        $allElementsTrue: [{
                                                            $map: {
                                                                input: "$$chunkDoc.max",
                                                                in: { $eq: [{ $type: '$$this' }, 'maxKey'] }
                                                            }
                                                        }]
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        }
    },
    getProjectionStage()
    ];

    // The main logic
    const bucketsNss = timeseriesCollDoc._id;
    const dbName = bucketsNss.substring(0, bucketsNss.indexOf('.'));
    const bucketsCollName = bucketsNss.substring(bucketsNss.indexOf('.') + 1);

    const readConcern = performStrictCheck
        ? { level: 'snapshot', atClusterTime: now }
        : { level: 'majority' };

    shardConn.getDB(dbName)[bucketsCollName]
        .aggregate(findNotOwnedDocsPipeline,
            {
                collation: { locale: "simple" },
                readConcern: readConcern
            })
        .forEach(notOwnedDoc => {
            // A not owned document may be legit if there is a pending range deletion task that
            // targets it.
            const matchingRangeDeletion =
                shardConn.getDB('config').rangeDeletions.find({
                    collectionUuid: timeseriesCollDoc.uuid,
                    'range.min': { $lte: notOwnedDoc.shardKeyValue },
                    $or: [{ 'range.max': { $gt: notOwnedDoc.shardKeyValue } }, { 'range.max': maxShardKeyValue }]
                },
                    {
                        collation: { locale: "simple" },
                        readConcern: readConcern
                    }).limit(1).toArray();
            if (matchingRangeDeletion.length === 0) {
                orphanDocumentIds.push(notOwnedDoc._id);
            }
        });

    return orphanDocumentIds;
};

// Main function.
function checkTimeseriesOrphansOnCluster(reportNamespace = '') {
    try {
        assert(configDB.runCommand({ isdbgrid: 1 }).ok, "Must be launched from a mongos node.");
    } catch (e) {
        if (e.codeName === 'CommandNotFound') {
            assert(false, "Must be launched from a mongos node.");
        } else {
            throw e;
        }
    }

    const balancerRoundResponse = configDB.getSiblingDB("admin").runCommand({ balancerStatus: 1 });
    assert(balancerRoundResponse.ok, `Failed to contact config server to check the balancer state.`);
    assert(!balancerRoundResponse.inBalancerRound, "Balancer must be stopped first.");

    let shardConns = getConnectionsToShards();
    let fullReportColl = null;
    print('*********');
    print(`Inspecting cluster...\n`);
    if (!reportNamespace) {
        print('No namespace for full report has been specified. The check will only print a summary on screen.');
    } else {
        const reportDbName = reportNamespace.substring(0, reportNamespace.indexOf('.'));
        const reportCollName = reportNamespace.substring(reportNamespace.indexOf('.') + 1);
        const reportCollIndex = { "orphanDocData.parentNamespace": 1, 'orphanDocData.foundIn': 1 };
        try {
            fullReportColl = configDB.getSiblingDB(reportDbName)[reportCollName];
        } catch (e) {
            assert(false, `Invalid format for report namespace: expected 'dbName.collName', received ${reportNamespace}`);
        }

        assert(!fullReportColl.countDocuments({}), `The namespace specified to store the full report must be empty!`);
        const collCreationOutcome = configDB.getSiblingDB(reportDbName).createCollection(reportCollName);
        assert(collCreationOutcome.ok, JSON.stringify(collCreationOutcome));
        fullReportColl.createIndex(reportCollIndex);
    }

    print(`Waiting up to 5 minutes for the completion of outstanding chunk migrations...`);

    for (let shardId in shardConns) {
        // Ensure that the shard  isn't still involved in any outstanding chunk migration.        
        const pauseBetweenChecks = 5 * 1000; // msecs
        const maxNumAttempts = 2;
        let outstandingMigrations = -1;
        for (let numAttempts = 0; numAttempts <= maxNumAttempts; ++numAttempts) {
            outstandingMigrations = shardConns[shardId].getDB('config').migrationCoordinators.countDocuments({});
            if (outstandingMigrations === 0 || numAttempts == maxNumAttempts) {
                break;
            }

            sleep(pauseBetweenChecks);

        }

        assert(!outstandingMigrations,
            `Unable to continue: shard ${shardId} still busy in a shard migration; retry later.`);
    }

    let numTotalOrphans = 0;
    for (let shardId in shardConns) {
        print(`[${shardId}] Inspecting shard content...`);
        configDB.collections.find({ _id: { $regex: "\.system\.buckets\." } })
            .forEach(timeseriesCollDoc => {
                const orphanDocumentIds = getOrphansForTimeseriesCollectionOnShard(
                    timeseriesCollDoc, shardId, shardConns[shardId]);
                if (orphanDocumentIds.length !== 0) {
                    numTotalOrphans += orphanDocumentIds.length;
                    print(`[${shardId}] [ERROR] ${orphanDocumentIds.length} orphan documents detected for collection '${timeseriesCollDoc._id}'`);
                    if (fullReportColl) {
                        let bulk = fullReportColl.initializeUnorderedBulkOp();
                        for (const orphanId of orphanDocumentIds) {
                            bulk.insert({
                                "orphanDocData": {
                                    "_id": orphanId,
                                    "parentNamespace": timeseriesCollDoc._id,
                                    "foundIn": shardId
                                }
                            });
                        }

                        bulk.execute();
                    }
                }
            });
        print(`[${shardId}] Shard inspection completed.\n`);
    }
    print(`Cluster inspection completed.  A total number of ${numTotalOrphans} orphan documents has been detected.`);
    print('*********');
};

function stageOrphanedTimeSeriesDocumentsForRecovery(orphanedDocsResults, namespace, staging_namespace) {
    // Parse db.coll namespaces into individual db and collection names, 
    // taking into account that collname can contain periods
    try {
        existing_ns = parseNamespace(namespace)
        staging_ns = parseNamespace(staging_namespace)
    } catch (error) {
        print(`[ERROR] - Namespaces should be of the form "db.collection"`)
        return
    }

    existingCollection = db.getSiblingDB(existing_ns.dbname).getCollection(existing_ns.collname)
    stagingCollection = db.getSiblingDB(staging_ns.dbname).getCollection(staging_ns.collname)

    // 1. Check if orphanedDocResults exists and exit otherwise. 
    results = db.getCollectionInfos({ "name": `${orphanedDocsResults}` })
    if (results.length == 0) {
        print(`[ERROR] - Results collection '${orphanedDocsResults}' does not exist.`)
        return
    }

    // 2. Check if results collection contains entries for namespace specified. 
    orphanBucketCount = db.getCollection(orphanedDocsResults).countDocuments({ "orphanDocData.parentNamespace": existing_ns.dbname + ".system.buckets." + existing_ns.collname })
    if (orphanBucketCount == 0) {
        print(`[ERROR] - No orphaned documents identified for collection ${namespace} in ${orphanedDocsResults}`)
        return
    }

    // 3.1 - Create the unsharded staging collection with the same timeseries options as the original collection 
    // We only grab ts_options in the event that any other setting may be defined 
    ts_options = getCollectionInfosFromNamespace(existing_ns)[0].options.timeseries
    db.getSiblingDB(staging_ns.dbname).createCollection(staging_ns.collname, { "timeseries": ts_options })

    // 4.0 - Move orphaned bucket documents from each shard into the staging bucket collections
    print(`Moving bucket documents to staging collection...\n`);
    let shardConns = getConnectionsToShards();
    var cur = db.getCollection(orphanedDocsResults).find({ "orphanDocData.parentNamespace": existing_ns.dbname + ".system.buckets." + existing_ns.collname })

    // For each document for the given namespace in the results collection
    var docCount = 0
    cur.forEach(function (orphanBucket) {
        // Parse namespace information for use in querying  
        foundIn = orphanBucket.orphanDocData.foundIn                    // Shard identifier 
        found_namespace = orphanBucket.orphanDocData.parentNamespace    // db.system.bucket.collname  
        bucket_collection = parseNamespace(found_namespace).collname    // system.bucket.collname 
        dbname = existing_ns.dbname

        foundShardConnection = shardConns[foundIn]
        stagingCollection = db.getSiblingDB(staging_ns.dbname).getCollection(`system.buckets.${staging_ns.collname}`)

        try {
            // Check if it exists in the staging collection (already migrated to staging collection)
            let staged_doc = stagingCollection.findOne({ "_id" : orphanBucket.orphanDocData._id })

            // Document has already been staged
            // We should confirm that it was removed from the underlying shard 
            if(staged_doc) {
                let delete_result = removeOrphanedBucketDocumentFromShard(foundShardConnection, dbname, bucket_collection, orphanBucket.orphanDocData._id)
                
                // Confirm that document was deleted
                if(delete_result.deletedCount == 1) {
                    log('INFO', `${found_namespace} - Deleted orphan bucket for already staged document with _id: ${orphanBucket.orphanDocData._id}`)
                }
            }

            // If document is not already staged - we need top obtain the document from the underlying shard
            // and then remove the orphaned bucket 
            if(!staged_doc) {
                orphanedBucketDoc = getOrphanedBucketDocumentFromShard(foundShardConnection, dbname, bucket_collection, orphanBucket.orphanDocData._id)

                // Only proceed if we actually found the bucket document - otherwise we could insert an empty document. 
                if(orphanedBucketDoc) {
                    // Insert document into the bucket collection of the newly created staging collection
                    let insert_res = stagingCollection.insertOne(orphanedBucketDoc)
                    docCount += 1

                    // Only delete the orphaned bucket if we inserted into the staging collection successfully. 
                    if(insert_res.acknowledged) {
                        let delete_result = removeOrphanedBucketDocumentFromShard(foundShardConnection, dbname, bucket_collection, orphanBucket.orphanDocData._id)
                        
                        if(delete_result.deletedCount != 1) {
                            log('ERROR', `${found_namespace} - Failed to delete orphan bucket for staged document with _id: ${orphanBucket.orphanDocData._id}`)
                        }
                    } else {
                        // This is probably redundant with the catch
                        log('ERROR', `${found_namespace} - Failed to stage bucket document with _id: ${orphanBucket.orphanDocData._id} - Error is: ${error}`)
                    }
                } else {
                    // We have a record in the results collection that: 
                    //  * Was not found in the staging collection, and 
                    //  * Was not found on the underlying shards
                    // Log an error indicating that this document is missing. 
                    log('ERROR', `${found_namespace} - Unable to find orphaned OR staged document with _id: ${orphanBucket.orphanDocData._id}`)
                }
            } 
        }
        catch (error) {
            log('ERROR', `${found_namespace} - Error encountered when staging bucket documents with _id ${orphanBucket.orphanDocData._id} - Error is: ${error}`)
            return
        } 

        // Print status messages every 1K documents
        if(docCount % 1000 == 0) {
            log('INFO', `${docCount} orphaned documents moved to staging collection ${staging_namespace}`)
        }
    })
    log('INFO', `${docCount} orphaned documents from ${namespace} copied to staging collection: ${staging_namespace}`)
}

function getOrphanedBucketDocumentFromShard(shardConnection, dbname, bucket_collection, _id) {
    return shardConnection.getDB(dbname).getCollection(bucket_collection).findOne({ "_id": _id })
}

function removeOrphanedBucketDocumentFromShard(shardConnection, dbname, bucket_collection, _id) {
    return shardConnection.getDB(dbname).getCollection(bucket_collection).deleteOne({ "_id" : _id })
}

function getCollectionInfosFromNamespace(namespace_ns) {
    return db.getSiblingDB(namespace_ns.dbname).getCollectionInfos({ "name": namespace_ns.collname })
}

// Parse a db.collection namespace into names, taking into account that a collection name can contain periods.
function parseNamespace(namespace) {
    names_split = namespace.split(".")
    if (names_split.length == 1) {
        throw new Error(`Invalid namespace - namespace should be of the form db.collection`)
    } else {

        res = {}
        res.ns = namespace
        res.dbname = names_split[0]
        res.collname = names_split.slice(1).join(".")
        return res
    }
}

function log(type, message) {
    let currentTime = new Date()
    console.log(`${currentTime.toISOString()} - [${type}] - ${message}`)
}