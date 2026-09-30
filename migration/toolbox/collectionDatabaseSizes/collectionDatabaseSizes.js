// Reports collection size, storage, indexes, collection type, and sharding information

db.getMongo().setReadPref("primary");

const excludeDatabases = ["admin", "config", "local"];

// Supported values: table, json, csv
const outputFormat = (
    typeof process !== "undefined" &&
    process.env &&
    process.env.OUTPUT_FORMAT
        ? process.env.OUTPUT_FORMAT
        : "table"
).toLowerCase();

if (!["table", "json", "csv"].includes(outputFormat)) {
    throw new Error(
        "Invalid OUTPUT_FORMAT. Use: table, json, or csv"
    );
}

function byteToMB(bytes) {
    if (bytes === null || bytes === undefined || isNaN(bytes)) {
        return null;
    }

    return parseFloat((Number(bytes) / 1024 / 1024).toFixed(2));
}

function byteToKB(bytes) {
    if (bytes === null || bytes === undefined || isNaN(bytes)) {
        return null;
    }

    return parseFloat((Number(bytes) / 1024).toFixed(2));
}

function displayValue(value) {
    if (value === null || value === undefined) {
        return "N/A";
    }

    return value;
}

function extractCompressor(collectionOptions) {
    if (!collectionOptions || typeof collectionOptions !== "object") {
        return null;
    }

    const storageEngine = collectionOptions.storageEngine || collectionOptions.wiredTiger || null;
    if (!storageEngine) {
        return null;
    }

    if (typeof storageEngine === "string") {
        const normalized = storageEngine.toLowerCase();
        if (normalized.includes("zstd")) {
            return "zstd";
        }
        if (normalized.includes("snappy")) {
            return "snappy";
        }
        if (normalized.includes("zlib")) {
            return "zlib";
        }
        if (normalized.includes("none")) {
            return "none";
        }
        return storageEngine;
    }

    if (typeof storageEngine === "object") {
        const blockCompressor =
            storageEngine.blockCompressor ||
            storageEngine.configString ||
            storageEngine.compressor ||
            (storageEngine.wiredTiger && storageEngine.wiredTiger.configString) ||
            null;

        if (typeof blockCompressor === "string") {
            const normalized = blockCompressor.toLowerCase();
            if (normalized.includes("zstd")) {
                return "zstd";
            }
            if (normalized.includes("snappy")) {
                return "snappy";
            }
            if (normalized.includes("zlib")) {
                return "zlib";
            }
            if (normalized.includes("none")) {
                return "none";
            }
            return blockCompressor;
        }
    }

    return null;
}

function extractCompressorFromStats(stats) {
    const creationString =
        stats && stats.wiredTiger && stats.wiredTiger.creationString;

    if (typeof creationString !== "string") {
        return null;
    }

    const match = creationString.match(
        /(?:^|,)block_compressor=([^,()]+)/i
    );

    return match
        ? extractCompressor({ storageEngine: match[1] })
        : null;
}

function getShardKey(databaseName, collectionName, isSharded) {
    if (isSharded !== true) {
        return null;
    }

    try {
        const shardedCollection = db.getSiblingDB("config").collections.findOne(
            {
                _id: databaseName + "." + collectionName
            },
            {
                key: 1,
                _id: 0
            }
        );

        if (!shardedCollection || !shardedCollection.key) {
            return null;
        }

        return JSON.stringify(shardedCollection.key);
    } catch (e) {
        return null;
    }
}

function getReusableStorageBytes(stats, metricName) {
    if (stats[metricName] !== null && stats[metricName] !== undefined) {
        return stats[metricName];
    }

    let shardTotal = 0;
    let shardCount = 0;
    const shardStats = stats.shards;

    if (shardStats && typeof shardStats === "object") {
        for (const shardName in shardStats) {
            if (!Object.prototype.hasOwnProperty.call(shardStats, shardName)) {
                continue;
            }

            shardCount++;

            const shardBlockManager =
                shardStats[shardName] &&
                shardStats[shardName].wiredTiger &&
                shardStats[shardName].wiredTiger["block-manager"];
            const shardValue =
                shardStats[shardName] &&
                shardStats[shardName][metricName] !== null &&
                shardStats[shardName][metricName] !== undefined
                    ? shardStats[shardName][metricName]
                    : shardBlockManager &&
                      shardBlockManager["file bytes available for reuse"];

            if (shardValue === null || shardValue === undefined || isNaN(shardValue)) {
                return null;
            }

            shardTotal += Number(shardValue);
        }
    }

    if (shardCount > 0) {
        return shardTotal;
    }

    const wiredTigerBlockManager =
        stats.wiredTiger && stats.wiredTiger["block-manager"];

    if (!wiredTigerBlockManager) {
        return null;
    }

    return wiredTigerBlockManager["file bytes available for reuse"] ?? null;
}

// collStats gained the freeStorage option in 5.0.6 (SERVER-62277).
function supportsFreeStorage() {
    try {
        const versionArray = db.serverBuildInfo().versionArray;

        if (!Array.isArray(versionArray) || versionArray.length < 3) {
            return false;
        }

        const [major, minor, patch] = versionArray;

        if (major !== 5) {
            return major > 5;
        }

        return minor > 0 || patch >= 6;
    } catch (e) {
        return false;
    }
}

const freeStorageSupported = supportsFreeStorage();

function isUnknownOptionError(e) {
    // 40415 is the server's "unknown field" error for unrecognized command options.
    return e.code === 40415 ||
        /unrecognized|unknown field|not supported/i.test(e.message || "");
}

function getCollectionStats(collection) {
    if (!freeStorageSupported) {
        return collection.stats();
    }

    try {
        return collection.stats({ freeStorage: true });
    } catch (e) {
        if (!isUnknownOptionError(e)) {
            throw e;
        }

        return collection.stats();
    }
}

function getCollectionInfoList(database) {
    try {
        return database.getCollectionInfos();
    } catch (e) {
        // Users without listCollections can still enumerate authorized names and types,
        // but collection options are unavailable to them.
        return database.getCollectionInfos({}, {
            authorizedCollections: true,
            nameOnly: true
        }).map(function(collectionInfo) {
            return {
                name: collectionInfo.name,
                type: collectionInfo.type,
                optionsUnavailable: true
            };
        });
    }
}

const databaseInfo = [];

const databases = db.adminCommand({ listDatabases: 1 }).databases.filter(function(database) {
    return !excludeDatabases.includes(database.name);
});

for (let i = 0; i < databases.length; i++) {
    const database = databases[i];
    const currentDb = db.getSiblingDB(database.name);

    const collections = getCollectionInfoList(currentDb).filter(function(collectionInfo) {
        // Views do not support collStats or listIndexes.
        if (collectionInfo.type === "view") {
            return false;
        }

        // Internal namespaces, including the system.buckets.* collections that would
        // double count time-series storage against the user-visible collection.
        return collectionInfo.name.indexOf("system.") !== 0;
    });

    collections.forEach(function(collectionInfo) {
        const collectionName = collectionInfo.name;

        try {
            const currentCollection = currentDb.getCollection(collectionName);

            const stats = getCollectionStats(currentCollection);

            const collectionOptions = collectionInfo.options || {};
            const optionsUnavailable = collectionInfo.optionsUnavailable === true;
            const compressor = optionsUnavailable ? null : extractCompressor(collectionOptions) || extractCompressorFromStats(stats);

            // Get index definitions
            const indexes = currentCollection.getIndexes();

            const uniqueIndexCount = indexes.filter(function(index) {
                return index.unique === true;
            }).length;

            // Time-series and clustered collections express expiry as a collection
            // option instead of a TTL index.
            const timeSeries = collectionOptions.timeseries;
            const clusteredIndex = collectionOptions.clusteredIndex;
            const hasTTLIndex = optionsUnavailable
                ? null
                : collectionOptions.expireAfterSeconds !== undefined ||
                  (timeSeries &&
                      timeSeries.expireAfterSeconds !== undefined) ||
                  (clusteredIndex &&
                      clusteredIndex.expireAfterSeconds !== undefined) ||
                  indexes.some(function(index) {
                      return index.expireAfterSeconds !== undefined;
                  });

            const isSharded =
                typeof stats.sharded === "boolean"
                    ? stats.sharded
                    : null;

            const shardKey = getShardKey(database.name, collectionName, isSharded);

            const freeDocumentStorage = getReusableStorageBytes(
                stats,
                "freeStorageSize"
            );

            databaseInfo.push({
                db: database.name,
                collection: collectionName,

                // Metrics report null when collStats omits them, so they render as N/A
                // rather than as a value the server never supplied.
                documentCount: stats.count ?? null,
                averageDocumentSizeBytes: stats.avgObjSize ?? null,
                averageDocumentSize_KB: byteToKB(stats.avgObjSize),

                // Logical data size
                size: stats.size ?? null,
                size_MB: byteToMB(stats.size),

                // Allocated document storage
                storageSize: stats.storageSize ?? null,
                storageSize_MB: byteToMB(stats.storageSize),

                // Index statistics
                numberOfIndexes: stats.nindexes ?? indexes.length,
                uniqueIndexCount: uniqueIndexCount,
                totalIndexSize: stats.totalIndexSize ?? null,
                totalIndexSize_MB: byteToMB(stats.totalIndexSize),

                // Free storage
                freeDocumentStorage: freeDocumentStorage,
                freeDocumentStorage_MB: byteToMB(freeDocumentStorage),

                // Collection properties
                isCapped: stats.capped === true,
                isClustered: optionsUnavailable
                    ? null
                    : collectionOptions.clusteredIndex !== undefined,
                isTimeSeries: optionsUnavailable
                    ? null
                    : collectionOptions.timeseries !== undefined,
                hasTTLIndex: hasTTLIndex,
                compressor: compressor || null,

                // Available reliably when connected through mongos
                isSharded: isSharded,
                shardKey: shardKey
            });
        } catch (e) {
            databaseInfo.push({
                db: database.name,
                collection: collectionName,
                error: e.message
            });
        }
    });
}

// Sort by logical data size, largest first
databaseInfo.sort(function(a, b) {
    return (b.size || 0) - (a.size || 0);
});

// JSON output
if (outputFormat === "json") {
    print(JSON.stringify(databaseInfo, null, 2));
}

// CSV output
else if (outputFormat === "csv") {
    const columns = [
        ["Database", "db"],
        ["Collection", "collection"],
        ["Documents", "documentCount"],
        ["Avg Document Size (KB)", "averageDocumentSize_KB"],
        ["Data Size (MB)", "size_MB"],
        ["Storage Size (MB)", "storageSize_MB"],
        ["Total Indexes", "numberOfIndexes"],
        ["Unique Indexes", "uniqueIndexCount"],
        ["Total Index Size (MB)", "totalIndexSize_MB"],
        ["Reusable Doc Storage (MB)", "freeDocumentStorage_MB"],
        ["Capped", "isCapped"],
        ["Clustered", "isClustered"],
        ["Time-Series", "isTimeSeries"],
        ["Has TTL Index", "hasTTLIndex"],
        ["Compressor", "compressor"],
        ["Sharded", "isSharded"],
        ["Shard Key", "shardKey"],
        ["Error", "error"]
    ];

    function csvValue(value) {
        if (value === null || value === undefined) {
            return '"N/A"';
        }

        return '"' + String(value).replace(/"/g, '""') + '"';
    }

    print(
        columns
            .map(function(column) {
                return csvValue(column[0]);
            })
            .join(",")
    );

    databaseInfo.forEach(function(info) {
        print(
            columns
                .map(function(column) {
                    let value = info[column[1]];

                    if (column[1] === "isSharded" && value === null) {
                        value = "unknown";
                    }

                    return csvValue(value);
                })
                .join(",")
        );
    });
}

// Table output
else {
    print(
        "Database | Collection | Docs | Avg Doc (KB) | Data (MB) | " +
        "Stor (MB) | Total Idx | Unique Idx | Idx Size (MB) | Reuse Doc (MB) | " +
        "Capped | Clustered | Time | TTL | Compressor | Sharded | Shard Key"
    );

    print(
        "------------------------------------------------------------------------------------------------------------------------------------------------------"
    );

    databaseInfo.forEach(function(info) {
        if (info.error) {
            print(
                info.db + " | " +
                info.collection + " | ERROR: " +
                info.error
            );
            return;
        }

        const shardedValue =
            info.isSharded === null
                ? "unknown"
                : info.isSharded;

        print(
            info.db + " | " +
            info.collection + " | " +
            displayValue(info.documentCount) + " | " +
            displayValue(info.averageDocumentSize_KB) + " | " +
            displayValue(info.size_MB) + " | " +
            displayValue(info.storageSize_MB) + " | " +
            displayValue(info.numberOfIndexes) + " | " +
            info.uniqueIndexCount + " | " +
            displayValue(info.totalIndexSize_MB) + " | " +
            displayValue(info.freeDocumentStorage_MB) + " | " +
            info.isCapped + " | " +
            displayValue(info.isClustered) + " | " +
            displayValue(info.isTimeSeries) + " | " +
            displayValue(info.hasTTLIndex) + " | " +
            displayValue(info.compressor) + " | " +
            shardedValue + " | " +
            displayValue(info.shardKey)
        );
    });
}
