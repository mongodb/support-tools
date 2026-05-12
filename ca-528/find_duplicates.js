// find_duplicates.js
// Step 2 of 2: For each candidate collection found by find_candidate_collections.js,
// run the expensive aggregation to detect actual cross-shard duplicates caused by
// SERVER-85346 (non-simple-collation unique indexes on sharded collections).
//
// Usage (all candidate collections):
//   mongosh "mongodb://127.0.0.1:27017" --quiet -f find_duplicates.js
//
// Usage (single collection — much faster on large clusters):
//   mongosh "mongodb://127.0.0.1:27017" --eval 'const TARGET_NS="mydb.mycoll";' -f find_duplicates.js

(function () {
    "use strict";

    const MAX_DUP_GROUPS = 100;   // max duplicate groups to report per index
    const SAMPLE_IDS_PER = 5;     // sample _ids shown per group

    // Optional: set via --eval 'const TARGET_NS="db.coll";' to scan one collection only.
    const targetNs = (typeof TARGET_NS !== "undefined") ? TARGET_NS : null;

    const configDB = db.getSiblingDB("config");

    function isNonSimpleCollation(c) {
        if (!c) return false;
        if (c.locale === "simple" || c.locale === undefined) return false;
        return true;
    }

    function shardKeyIsPrefix(shardKey, indexKey) {
        const skFields = Object.keys(shardKey);
        const ixFields = Object.keys(indexKey);
        if (skFields.length > ixFields.length) return false;
        return skFields.every((f, i) => ixFields[i] === f);
    }

    let shardedColls = configDB.collections.find({
        dropped: { $ne: true },
        key: { $exists: true }
    }).toArray();

    if (targetNs) {
        shardedColls = shardedColls.filter(c => (c._id || c.ns) === targetNs);
        if (shardedColls.length === 0) {
            print("ERROR: namespace '" + targetNs + "' not found in config.collections.");
            quit(1);
        }
        print("Scanning 1 collection (TARGET_NS=" + targetNs + ") for duplicates...\n");
    } else {
        print("Scanning " + shardedColls.length + " sharded collection(s) for duplicates...\n");
        print("Tip: run find_candidate_collections.js first to identify specific collections,");
        print("     then target one with: --eval 'const TARGET_NS=\"db.coll\";' -f find_duplicates.js\n");
    }

    let totalCandidateIndexes = 0;
    let totalDuplicateGroups  = 0;
    const affectedCollections = [];

    for (const collDoc of shardedColls) {
        const nss = collDoc._id || collDoc.ns;
        if (!nss) continue;

        const dotIdx   = nss.indexOf(".");
        const dbName   = nss.substring(0, dotIdx);
        const collName = nss.substring(dotIdx + 1);
        if (!dbName || !collName) continue;

        if (!targetNs && ["config", "admin", "local"].includes(dbName)) continue;

        const shardKey = collDoc.key;
        const targetDB = db.getSiblingDB(dbName);
        const coll     = targetDB.getCollection(collName);

        let collDefaultCollation = null;
        try {
            const collInfo = targetDB.getCollectionInfos({ name: collName });
            if (collInfo.length > 0 && collInfo[0].options && collInfo[0].options.collation) {
                collDefaultCollation = collInfo[0].options.collation;
            }
        } catch (e) {
            print("WARNING: could not get collection info for " + nss + ": " + e);
            continue;
        }

        let indexes;
        try {
            indexes = coll.getIndexes();
        } catch (e) {
            print("WARNING: could not list indexes for " + nss + ": " + e);
            continue;
        }

        const candidates = indexes.filter(idx => {
            const eff = idx.collation || collDefaultCollation || null;
            return isNonSimpleCollation(eff) && idx.unique && shardKeyIsPrefix(shardKey, idx.key);
        });

        if (candidates.length === 0) continue;

        totalCandidateIndexes += candidates.length;
        print("── Collection: " + nss);
        print("   Shard key: " + EJSON.stringify(shardKey));
        print("   " + candidates.length + " candidate index(es)\n");

        let collDuplicates = 0;

        candidates.forEach(idx => {
            const effCollation = idx.collation || collDefaultCollation;
            const keyFields    = Object.keys(idx.key);

            print("   Index: " + idx.name);
            print("     Key:       " + EJSON.stringify(idx.key));
            print("     Unique:    " + (idx.unique ? "yes" : "no (may have been made unique via collMod on shards)"));
            print("     Collation: " + EJSON.stringify(effCollation));

            const projectSpec = { _id: 1 };
            keyFields.forEach(f => { projectSpec[f] = 1; });

            const groupId = {};
            keyFields.forEach(f => { groupId[f] = "$" + f; });

            const pipeline = [
                { $project: projectSpec },
                {
                    $group: {
                        _id: groupId,
                        count: { $sum: 1 },
                        sampleIds: { $push: "$_id" }
                    }
                },
                { $match: { count: { $gt: 1 } } },
                {
                    $project: {
                        count: 1,
                        sampleIds: { $slice: ["$sampleIds", SAMPLE_IDS_PER] }
                    }
                },
                { $limit: MAX_DUP_GROUPS }
            ];

            let dupGroups;
            try {
                dupGroups = coll.aggregate(pipeline, {
                    allowDiskUse: true,
                    collation: effCollation
                }).toArray();
            } catch (e) {
                print("     ERROR running duplicate aggregation: " + e + "\n");
                return;
            }

            if (dupGroups.length === 0) {
                print("     Result: NO duplicates found.\n");
            } else {
                collDuplicates += dupGroups.length;
                print("     Result: " + dupGroups.length + " duplicate group(s) found"
                      + (dupGroups.length >= MAX_DUP_GROUPS ? " (capped)" : "")
                      + ":\n");
                dupGroups.forEach(g => {
                    print("       Key values: " + EJSON.stringify(g._id));
                    print("       Count:      " + g.count);
                    print("       Sample _ids: " + EJSON.stringify(g.sampleIds));
                    print("");
                });
            }
        });

        if (collDuplicates > 0) {
            totalDuplicateGroups += collDuplicates;
            affectedCollections.push(nss);
        }
    }

    print("============================================================");
    print("Collections scanned:      " + (targetNs ? 1 : shardedColls.length));
    print("Candidate indexes found:  " + totalCandidateIndexes);
    print("Duplicate groups found:   " + totalDuplicateGroups);

    if (totalDuplicateGroups > 0) {
        print("Affected collections:     " + affectedCollections.join(", "));
        print("");
        print("==> DUPLICATES DETECTED — this cluster is affected by SERVER-85346.");
        quit(1);
    } else {
        print("");
        print("==> No cross-shard collation duplicates found.");
        quit(0);
    }
})();
