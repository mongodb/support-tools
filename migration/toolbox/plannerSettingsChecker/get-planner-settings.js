/* global db, print, printjson, quit, _mode */

/*
 * get-planner-settings.js
 *
 * Collect either:
 *   - index filters
 *   - query settings
 *
 * This script only returns collections/namespaces where a positive result exists.
 *
 * Set mode with:
 *   mongosh --quiet --eval 'var _mode="indexFilters"' get-planner-settings.js
 *   mongosh --quiet --eval 'var _mode="querySettings"' get-planner-settings.js
 *
 * Optional values:
 *   _mode = "indexFilters"   // default
 *   _mode = "querySettings"
 *
 * Notes:
 *   - "indexFilters" uses planCacheListFilters (legacy mechanism, all versions).
 *   - "querySettings" uses the $querySettings aggregation stage and requires
 *     MongoDB 8.0+ and cluster-admin level privileges.
 */

// Resolve the mode BEFORE entering the strict-mode IIFE. Assigning to an
// undeclared identifier inside "use strict" throws a ReferenceError, so the
// default must be established here on the global object.
if (typeof _mode === "undefined") {
    globalThis._mode = "indexFilters";
}

(function () {
    "use strict";

    function getCollectionNames(database) {
        var collectionNames = [];

        database.getCollectionInfos({ "type": "collection" }).forEach(function (collectionInfo) {
            var name = collectionInfo.name;

            if (name.indexOf("system.") === 0) {
                return;
            }

            if (database.getName() === "local") {
                if (name === "startup_log" || name.indexOf("replset.") === 0) {
                    return;
                }
            }

            collectionNames.push(name);
        });

        return collectionNames;
    }

    function getCollectionIndexFilters(database, collectionName) {
        var res = {
            db: database.getName(),
            collection: collectionName,
            namespace: database.getName() + "." + collectionName,
            hasIndexFilters: false,
            indexFilterCount: 0,
            indexFilters: []
        };

        try {
            var cmd = database.runCommand({
                planCacheListFilters: collectionName
            });

            if (!cmd.ok) {
                res.error = cmd;
                return res;
            }

            if (cmd.filters && Array.isArray(cmd.filters)) {
                res.indexFilters = cmd.filters;
            } else if (cmd.indexFilters && Array.isArray(cmd.indexFilters)) {
                res.indexFilters = cmd.indexFilters;
            }

            res.indexFilterCount = res.indexFilters.length;
            res.hasIndexFilters = res.indexFilterCount > 0;
        } catch (e) {
            res.error = e.message;
        }

        return res;
    }

    function getAllQuerySettings() {
        var res = {
            ok: false,
            querySettings: []
        };

        try {
            var cmd = db.adminCommand({
                aggregate: 1,
                pipeline: [
                    { $querySettings: {} }
                ],
                cursor: {}
            });

            if (!cmd.ok) {
                res.error = cmd;
                return res;
            }

            if (cmd.cursor && cmd.cursor.firstBatch) {
                res.querySettings = cmd.cursor.firstBatch;
            }

            res.ok = true;
        } catch (e) {
            res.error = e.message;
        }

        return res;
    }

    function buildNamespaceMap(querySettings) {
        var namespaceMap = {};

        querySettings.forEach(function (entry) {
            var ns = null;

            if (entry.namespace) {
                ns = entry.namespace;
            } else if (entry.representativeQuery && entry.representativeQuery.namespace) {
                ns = entry.representativeQuery.namespace;
            }

            if (!ns) {
                ns = "unknown";
            }

            if (!namespaceMap[ns]) {
                namespaceMap[ns] = [];
            }

            namespaceMap[ns].push(entry);
        });

        return namespaceMap;
    }

    function collectIndexFilters() {
        var allResults = [];
        var dbs = db.getMongo().getDBs();

        if (!dbs.databases) {
            return allResults;
        }

        dbs.databases.forEach(function (dbInfo) {
            var database = db.getSiblingDB(dbInfo.name);
            var collections;

            try {
                collections = getCollectionNames(database);
            } catch (e) {
                return;
            }

            collections.forEach(function (collectionName) {
                var result = getCollectionIndexFilters(database, collectionName);

                if (result.hasIndexFilters) {
                    allResults.push(result);
                }
            });
        });

        return allResults;
    }

    function collectQuerySettings() {
        var allResults = [];
        var allQuerySettingsResult = getAllQuerySettings();

        if (!allQuerySettingsResult.ok) {
            return {
                error: allQuerySettingsResult.error,
                results: []
            };
        }

        var namespaceMap = buildNamespaceMap(allQuerySettingsResult.querySettings);

        Object.keys(namespaceMap).forEach(function (namespace) {
            if (namespace === "unknown") {
                allResults.push({
                    namespace: namespace,
                    hasQuerySettings: true,
                    querySettingsCount: namespaceMap[namespace].length,
                    querySettings: namespaceMap[namespace]
                });
                return;
            }

            var firstDot = namespace.indexOf(".");
            var dbName;
            var collectionName;

            if (firstDot === -1) {
                dbName = namespace;
                collectionName = "";
            } else {
                dbName = namespace.substring(0, firstDot);
                collectionName = namespace.substring(firstDot + 1);
            }

            allResults.push({
                db: dbName,
                collection: collectionName,
                namespace: namespace,
                hasQuerySettings: true,
                querySettingsCount: namespaceMap[namespace].length,
                querySettings: namespaceMap[namespace]
            });
        });

        return {
            totalQuerySettingsReturned: allQuerySettingsResult.querySettings.length,
            results: allResults
        };
    }

    function printUsageAndExit() {
        print("");
        print("Usage:");
        print("  mongosh --quiet --eval 'var _mode=\"indexFilters\"' get-planner-settings.js");
        print("  mongosh --quiet --eval 'var _mode=\"querySettings\"' get-planner-settings.js");
        print("");
        print("Valid _mode values:");
        print("  indexFilters");
        print("  querySettings");
        quit(1);
    }

    if (_mode !== "indexFilters" && _mode !== "querySettings") {
        print("Invalid _mode: " + _mode);
        printUsageAndExit();
    }

    if (_mode === "indexFilters") {
        var indexFilterResults = collectIndexFilters();

        printjson({
            generatedAt: new Date(),
            host: db.getMongo().host,
            mode: _mode,
            summary: {
                collectionsWithIndexFilters: indexFilterResults.length
            },
            results: indexFilterResults
        });
        return;
    }

    var querySettingsResults = collectQuerySettings();

    if (querySettingsResults.error) {
        printjson({
            generatedAt: new Date(),
            host: db.getMongo().host,
            mode: _mode,
            error: querySettingsResults.error,
            results: []
        });
        return;
    }

    printjson({
        generatedAt: new Date(),
        host: db.getMongo().host,
        mode: _mode,
        summary: {
            namespacesWithQuerySettings: querySettingsResults.results.length,
            totalQuerySettingsReturned: querySettingsResults.totalQuerySettingsReturned
        },
        results: querySettingsResults.results
    });
}());
