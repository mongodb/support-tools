// SERVER-86622 Remediation Script. To be run by MongoDB Experts only.

// Connect to a mongos instance using mongosh

// Get the connection string, database name, and collection name from
// command-line arguments Specify the following options including optional [fix]
// in given order. Any extra options or arguments needed to connect must be
// provided at the end.
const args = process.argv.slice(2);

if (args.length < 2) {
  print(
      'Usage: mongosh <connection_string> <script.js> [<dbName> <collName> [fix]]');
  quit(1);
}

const dbName = args[2];    // Database name
const collName = args[3];  // Collection name
if (dbName && !collName) {
  print('Error executing: No collName specified.');
  exit(1);
}
const fullCollName = dbName && collName ? `${dbName}.${collName}` : null;
const shouldFix = args.length >= 5 &&
    args[4] === 'fix';  // Check if the user wants to fix inconsistencies

let allInconsistencies = [];

// Create UUID values for chunk operations
const uuid = 'caefe266-6835-4fd1-8d93-f1795487e3d0';
const uuidAfter = 'caefe266-6835-4fd1-8d93-f1795487e3d1';
const uuidValue = UUID(uuid);
const uuidValueAfter = UUID(uuidAfter);

function checkMongoDBVersion() {
  const version = db.version();
  print(`MongoDB version: ${version}`);
  return version;
}

function checkMetadataConsistency(collectionName) {
  print('Running checkMetadataConsistency command ');
  const result = db.runCommand({checkMetadataConsistency: 1});
  if (result.ok) {
    const inconsistencies = result.cursor.firstBatch;
    // Filter for inconsistencies of type "MissingLocalCollection"
    const missingLocalCollections = inconsistencies.filter(
        inconsistency => inconsistency.type === 'MissingLocalCollection' &&
            (!collectionName ||
             inconsistency.details.namespace === collectionName));
    if (missingLocalCollections.length > 0) {
      print('Inconsistencies found for the specified collection(s):');
      print(JSON.stringify(
          missingLocalCollections, null,
          2));  // Pretty print the inconsistencies
      allInconsistencies.push(...missingLocalCollections.map(
          inconsistency => inconsistency.details.namespace));
      return missingLocalCollections;
    } else {
      print(
          'No inconsistencies of type \'MissingLocalCollection\' found for the specified collection(s).');
      return false;
    }
  } else {
    print(`Error running checkMetadataConsistency: ${JSON.stringify(result)}`);
    return false;  // Error occurred
  }
}

function getPrimaryShard() {
  const dbStatus = db.getSiblingDB('config').databases.findOne({_id: dbName});
  if (!dbStatus) {
    print('Could not determine the primary shard for the database.');
    quit(1);
  }
  return dbStatus.primary;
}

function listCollectionsOnPrimary(databaseName) {
  const collectionsOnPrimary =
      db.getSiblingDB(databaseName).runCommand({listCollections: 1});
  if (!collectionsOnPrimary.ok) {
    print(`Error listing collections for ${databaseName}: ${
        JSON.stringify(collectionsOnPrimary)}`);
    quit(1);
  }
  return collectionsOnPrimary.cursor.firstBatch.map(
      coll => databaseName + '.' + coll.name);
}

function getConfigCollections(dbName = null) {
  const query = {_id: {$not: /^config\.system\./}};

  // If a database name is provided, filter collections by that database
  if (dbName) {
    query._id = {$regex: `^${dbName}\\.`};
  }
  return db.getSiblingDB('config').collections.find(query).toArray();
}

function findInconsistencies(primaryCollections, configCollectionNames) {
  return configCollectionNames.filter(
      coll => !primaryCollections.includes(coll));
}

function findOriginalShard(collectionName, shardKeyValue) {
  const explainOutput = db.getSiblingDB(dbName)[collectionName]
                            .find(shardKeyValue)
                            .explain('queryPlanner');
  if (explainOutput.queryPlanner.winningPlan.shards) {
    // Check if there is more than one shard
    if (explainOutput.queryPlanner.winningPlan.shards.length > 1) {
      print('Error: The query targets multiple shards. Exiting script.');
      quit(1);
    }
    return explainOutput.queryPlanner.winningPlan.shards[0]
        .shardName;  // Get the shard name from the winning plan
  }
  return null;
}

function executeSplit(collectionName, chunkKey) {
  const result = db.adminCommand({split: collectionName, middle: chunkKey});
  if (!result.ok) {
    print(`Error splitting chunk: ${JSON.stringify(result)}`);
    quit(1);
  }
}

function executeMoveChunk(collectionName, moveChunkKey, targetShard) {
  const result = db.adminCommand({
    moveChunk: collectionName,
    find: moveChunkKey,
    to: targetShard,
    _waitForDelete: true
  });
  if (!result.ok) {
    print(`Error moving chunk: ${JSON.stringify(result)}`);
    quit(1);
  }
}

function remediateInconsistencies(collectionName) {
  const configCollections = getConfigCollections(dbName);
  const collectionInfo = configCollections.find(c => c._id === collectionName);
  if (!collectionInfo || !collectionInfo.key) {
    print(`Error performing remediation. No shard key found for collection: ${
        collectionName}`);
    exit(1);
  }

  const shardKey = collectionInfo.key;
  const shardKeyFields = Object.keys(shardKey);
  const primaryShard = getPrimaryShard();
  if (!primaryShard) {
    print('Error executing script: Primary shard could not be determined.');
    quit(1);
  }
  const chunkKey = prepareChunkKeysForSplit(shardKey, shardKeyFields);
  if (!chunkKey) {
    print('Error executing script: Unable to prepare chunk key for split.');
    exit(1);
  }
  const firstSplitChunkKey = JSON.parse(JSON.stringify(chunkKey));
  if (db[collName].findOne(firstSplitChunkKey) !== null) {
    print(
        `Error executing: A document is already present with the given shard key: ${
            firstSplitChunkKey}`);
    quit(1);
  }
  performChunkSplits(collectionName, shardKey, shardKeyFields, chunkKey);
  const originalShard = findOriginalShard(collName, firstSplitChunkKey);
  if (!originalShard) {
    print('Error executing script: Original shard could not be determined.');
    exit(1);
  }
  moveChunks(collectionName, firstSplitChunkKey, primaryShard, originalShard);
  printOperationSummary(collectionName, shardKey, primaryShard, originalShard);
}

function prepareChunkKeysForSplit(shardKey, shardKeyFields) {
  let chunkKey = {};
  if (shardKeyFields.length === 0) return {chunkKey: null};
  const hasHashKey = shardKeyFields.some(field => shardKey[field] === 'hashed');
  if (hasHashKey) {
    shardKeyFields.forEach(field => {
      chunkKey[field] = (shardKey[field] === 'hashed') ?
          NumberLong('8048657584022293446') :
          null;
    });
  } else {
    shardKeyFields.forEach((field, index) => {
      chunkKey[field] = (index === 0) ? uuidValue : null;
    });
  }
  return chunkKey;
}

function performChunkSplits(
    collectionName, shardKey, shardKeyFields, chunkKey) {
  const hasHashKey = shardKeyFields.some(field => shardKey[field] === 'hashed');
  if (hasHashKey) {
    print(`Executing hash-based shard key chunk splits for collection ${
        collectionName}...`);
    executeSplit(collectionName, chunkKey);
    shardKeyFields.forEach(field => {
      chunkKey[field] = (shardKey[field] === 'hashed') ?
          NumberLong('8048657584022293447') :
          null;
    });
    executeSplit(collectionName, chunkKey);
  } else {
    print(`Executing range-based shard key chunk splits for collection ${
        collectionName}...`);
    executeSplit(collectionName, chunkKey);
    chunkKey[shardKeyFields[0]] = uuidValueAfter;
    executeSplit(collectionName, chunkKey);
  }
}

function moveChunks(collectionName, moveChunkKey, primaryShard, originalShard) {
  print(`Moving chunk containing [${uuid}, ${uuidAfter}) to primary shard ${
      primaryShard} for collection ${collectionName} from ${
      originalShard}... `);
  executeMoveChunk(collectionName, moveChunkKey, primaryShard);
  print(`Moving the chunk containing [${uuid}, ${
      uuidAfter}) to original shard ${originalShard} for collection ${
      collectionName} from primary shard ${primaryShard}... `);
  executeMoveChunk(collectionName, moveChunkKey, originalShard);
}

function printOperationSummary(
    collectionName, shardKey, primaryShard, originalShard) {
  print('---- Operation Summary ----');
  print(`- Collection: ${collectionName}`);
  print(`- Shard Key: ${JSON.stringify(shardKey)}`);
  print(`- Primary Shard: ${primaryShard}`);
  print(`- Original Shard: ${originalShard}`);
  print('---------------------------');
}

function checkAllShardedCollections(majorVersion) {
  const configCollections = getConfigCollections();
  // Starting 8.0, unsharded collections are tracked in config.collections if
  // they were moved using moveCollection
  const shardedCollections = configCollections.map(coll => coll._id);

  if (majorVersion >= 8) {
    print(
        'Checking all sharded collections for inconsistencies at the cluster level...');
    const result = db.adminCommand({checkMetadataConsistency: 1});
    if (result.ok) {
      const cursor = result.cursor;
      let inconsistencies = [];
      inconsistencies = inconsistencies.concat(cursor.firstBatch);

      // Filter for inconsistencies of type "MissingLocalCollection"
      const missingLocalCollections = inconsistencies.filter(
          inconsistency => inconsistency.type === 'MissingLocalCollection');
      if (missingLocalCollections.length > 0) {
        print('Inconsistencies of type "MissingLocalCollection" found:');
        print(JSON.stringify(missingLocalCollections, null, 2));
        allInconsistencies.push(...missingLocalCollections.map(
            inconsistency => inconsistency.details.namespace));
      } else {
        print(
            'No inconsistencies of type "MissingLocalCollection" found across all collections.');
      }
    }
  } else {
    shardedCollections.forEach(collectionName => {
      print(`Checking collection: ${collectionName}`);
      const dbName = collectionName.split('.')[0];
      const primaryCollections = listCollectionsOnPrimary(dbName);
      const configCollectionNames =
          getConfigCollections().map(coll => coll._id);
      const inconsistencies =
          findInconsistencies(primaryCollections, configCollectionNames);
      if (inconsistencies.includes(collectionName)) {
        print(`Inconsistencies found for collection: ${collectionName}`);
        allInconsistencies.push(collectionName);
      } else {
        print(`No inconsistencies found for collection: ${collectionName}`);
      }
    });
  }
}

const version = checkMongoDBVersion();
const majorVersion = version.split('.').map(Number)[0];

if (!dbName) {
  // If no dbName is provided, check all sharded collections
  checkAllShardedCollections(majorVersion);
} else {
  use(dbName);
  print(`Using database: ${dbName}`);

  if (majorVersion >= 8) {
    const inconsistencies = checkMetadataConsistency(fullCollName);
    if (inconsistencies) {
      print('Inconsistencies found: ' + JSON.stringify(inconsistencies));
      if (shouldFix) {  // Check if the user wants to fix inconsistencies
        print('Remediating inconsistencies...');
        remediateInconsistencies(fullCollName);
      } else {
        print(
            'No remediation performed. Use \'fix\' to remediate inconsistencies.');
      }
    } else {
      print('No inconsistencies found.');
    }
  } else {
    print(
        'MongoDB version is lower than 8.0. Running listCollections command...');
    const primaryCollections = listCollectionsOnPrimary(dbName);
    print(
        `Collections on primary shard: ${JSON.stringify(primaryCollections)}`);

    const configCollections = getConfigCollections(dbName);
    const configCollectionNames = configCollections.map(coll => coll._id);
    print(`Collections in config.collections: ${
        JSON.stringify(configCollectionNames)}`);

    const inconsistencies =
        findInconsistencies(primaryCollections, configCollectionNames);
    if (inconsistencies.length > 0) {
      print('Inconsistencies found: ' + JSON.stringify(inconsistencies));
      allInconsistencies.push(...inconsistencies);

      // Check if the specified collection is in the list of inconsistencies
      if (inconsistencies.includes(fullCollName)) {
        if (shouldFix) {  // Check if the user wants to fix inconsistencies
          print('Remediating inconsistencies...');
          remediateInconsistencies(fullCollName);
        } else {
          print(`Collection ${
              fullCollName} is inconsistent. Use 'fix' to remediate inconsistencies.`);
        }
      } else {
        print(`Collection ${
            fullCollName} is not in the list of inconsistencies.`);
      }
    } else {
      print(
          'No inconsistencies found between primary shard and config.collections.');
    }
  }
}

if (allInconsistencies.length > 0) {
  print('---- Inconsistencies Summary ----');
  print(JSON.stringify(allInconsistencies));
} else {
  print('No inconsistencies found across all checked collections.');
}

print('---------------------------');
print('Script execution completed.');
print('---------------------------');
