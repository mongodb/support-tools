// find_candidate_collections.js
// Step 1 of 2: Fast metadata-only scan to find sharded collections that may be
// affected by SERVER-85346 (non-simple-collation unique indexes). No aggregations
// are run — completes in seconds even on large clusters.
//
// Run Step 2 (find_duplicates.js) against the collections listed here.
//
// Usage:
//   mongosh "mongodb://127.0.0.1:27017" --quiet -f find_candidate_collections.js

(function () {
    "use strict";

    const configDB = db.getSiblingDB("config");

    function isNonSimpleCollation(c) {
        if (!c) return false;
        if (c.locale === "simple" || c.locale === undefined) return false;
        return true;
    }

    const shardedColls = configDB.collections.find({
        dropped: { $ne: true },
        key: { $exists: true }
    }).toArray();

    print("Scanning " + shardedColls.length + " sharded collection(s) for candidate indexes...\n");

    let totalCandidateIndexes = 0;
    const candidateNss = [];

    for (const collDoc of shardedColls) {
        const nss = collDoc._id || collDoc.ns;
        if (!nss) continue;

        const dotIdx   = nss.indexOf(".");
        const dbName   = nss.substring(0, dotIdx);
        const collName = nss.substring(dotIdx + 1);
        if (!dbName || !collName) continue;

        if (["config", "admin", "local"].includes(dbName)) continue;

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

        const candidateIndexes = indexes.filter(idx => {
            const eff = idx.collation || collDefaultCollation || null;
            return isNonSimpleCollation(eff);
        });

        if (candidateIndexes.length === 0) continue;

        totalCandidateIndexes += candidateIndexes.length;
        candidateNss.push(nss);

        print("── " + nss);
        print("   Shard key: " + EJSON.stringify(shardKey));
        candidateIndexes.forEach(idx => {
            const eff = idx.collation || collDefaultCollation;
            print("   Index: " + idx.name
                + "  key: " + EJSON.stringify(idx.key)
                + "  unique: " + (idx.unique ? "yes" : "no")
                + "  collation: " + EJSON.stringify(eff));
        });
        print("");
    }

    print("============================================================");
    print("Collections scanned:     " + shardedColls.length);
    print("Candidate indexes found: " + totalCandidateIndexes);
    print("Collections to check:    " + candidateNss.length);

    if (candidateNss.length > 0) {
        print("");
        print("==> Run find_duplicates.js to check these collection(s) for actual duplicates.");
        print("    To check a single collection, pass TARGET_NS before the script:");
        print("    mongosh <uri> --eval 'const TARGET_NS=\"db.coll\";' -f find_duplicates.js");
        quit(0);
    } else {
        print("");
        print("==> No sharded collections with non-simple-collation indexes found.");
        quit(0);
    }
})();
