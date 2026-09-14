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

    const wiredTigerBlockManager =
        stats.wiredTiger && stats.wiredTiger["block-manager"];

    if (!wiredTigerBlockManager) {
        return null;
    }

    return wiredTigerBlockManager["file bytes available for reuse"] ?? null;
}

const databaseInfo = [];

const databases = db.adminCommand({ listDatabases: 1 }).databases.filter(function(database) {
    return !excludeDatabases.includes(database.name);
});

for (let i = 0; i < databases.length; i++) {
    const database = databases[i];
    const currentDb = db.getSiblingDB(database.name);
    const collections = currentDb.getCollectionNames();

    collections.forEach(function(collectionName) {
        try {
            const currentCollection = currentDb.getCollection(collectionName);

            const stats = currentCollection.stats({
                freeStorage: 1
            });

            // Get collection metadata
            const collectionInfoList = currentDb.getCollectionInfos({
                name: collectionName
            });

            const collectionInfo =
                collectionInfoList.length > 0
                    ? collectionInfoList[0]
                    : {};

            const collectionOptions = collectionInfo.options || {};
            const compressor = extractCompressor(collectionOptions);

            // Get index definitions
            const indexes = currentCollection.getIndexes();

            const uniqueIndexCount = indexes.filter(function(index) {
                return index.unique === true;
            }).length;

            // Check whether at least one TTL index exists
            const hasTTLIndex = indexes.some(function(index) {
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

                // Document statistics
                documentCount: stats.count ?? 0,
                averageDocumentSizeBytes: stats.avgObjSize ?? 0,
                averageDocumentSize_KB: byteToKB(stats.avgObjSize),

                // Logical data size
                size: stats.size ?? 0,
                size_MB: byteToMB(stats.size),

                // Allocated document storage
                storageSize: stats.storageSize ?? 0,
                storageSize_MB: byteToMB(stats.storageSize),

                // Index statistics
                numberOfIndexes: stats.nindexes ?? 0,
                uniqueIndexCount: uniqueIndexCount,
                totalIndexSize: stats.totalIndexSize ?? 0,
                totalIndexSize_MB: byteToMB(stats.totalIndexSize),

                // Free storage
                freeDocumentStorage: freeDocumentStorage,
                freeDocumentStorage_MB: byteToMB(freeDocumentStorage),

                // Collection properties
                isCapped: stats.capped === true,
                isClustered: collectionOptions.clusteredIndex !== undefined,
                isTimeSeries: collectionOptions.timeseries !== undefined,
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
            info.documentCount + " | " +
            displayValue(info.averageDocumentSize_KB) + " | " +
            displayValue(info.size_MB) + " | " +
            displayValue(info.storageSize_MB) + " | " +
            info.numberOfIndexes + " | " +
            info.uniqueIndexCount + " | " +
            displayValue(info.totalIndexSize_MB) + " | " +
            displayValue(info.freeDocumentStorage_MB) + " | " +
            info.isCapped + " | " +
            info.isClustered + " | " +
            info.isTimeSeries + " | " +
            info.hasTTLIndex + " | " +
            displayValue(info.compressor) + " | " +
            shardedValue + " | " +
            displayValue(info.shardKey)
        );
    });
}
