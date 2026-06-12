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

// Mode constants, defined once and reused for defaulting, validation,
// branching, usage text, and documentation references to prevent drift.
var MODE_INDEX_FILTERS = "indexFilters";
var MODE_QUERY_SETTINGS = "querySettings";

// Resolve the mode BEFORE entering the strict-mode IIFE. Assigning to an
// undeclared identifier inside "use strict" throws a ReferenceError, so the
// default must be established here.
if (typeof _mode === "undefined") {
    var _mode = MODE_INDEX_FILTERS;
}

(function () {
    "use strict";

    function getHostInfo() {
        // db.getMongo().host is not populated in mongosh, so fall back to the
        // host reported by hello() (set on replica sets/sharded clusters) and
        // then to the host portion of the connection URI for standalones.
        try {
            var me = db.hello().me;
            if (me) {
                return me;
            }
        } catch (e) {
            // ignore and fall through to the URI-based resolution
        }

        try {
            var uri = db.getMongo()._uri;
            if (uri) {
                var withoutScheme = uri.replace(/^mongodb(\+srv)?:\/\//, "");
                var hostPart = withoutScheme.split("/")[0].split("?")[0];

                // Strip any userinfo ("username:password@") so connection-string
                // credentials are never echoed into the report.
                if (hostPart.indexOf("@") !== -1) {
                    hostPart = hostPart.substring(hostPart.lastIndexOf("@") + 1);
                }

                if (hostPart) {
                    return hostPart;
                }
            }
        } catch (e) {
            // ignore and fall through to the default
        }

        return "unknown";
    }

    function getCollectionNames(database) {
        var collectionNames = [];

        // Use nameOnly to avoid scanning collection metadata; only the name and
        // type are needed here, both of which are still returned in this mode.
        database.getCollectionInfos({ "type": "collection" }, {nameOnly:true}).forEach(function (collectionInfo) {
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
            var admin = db.getSiblingDB("admin");

            // Use the aggregate() helper with toArray() so the driver iterates
            // the full cursor; results that span multiple batches are not
            // silently truncated to just the first batch.
            res.querySettings = admin.aggregate([
                { $querySettings: {} }
            ]).toArray();

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
            } else if (entry.representativeQuery) {
                var rq = entry.representativeQuery;

                if (rq.namespace) {
                    ns = rq.namespace;
                } else if (rq["$db"]) {
                    // The $querySettings output describes the namespace via the
                    // command shape: the database is in "$db" and the collection
                    // is the value of the command name (find/aggregate/etc.).
                    var commandKeys = [
                        "find", "aggregate", "count", "distinct",
                        "update", "delete", "findAndModify"
                    ];
                    var commandName = null;
                    var target = null;

                    for (var i = 0; i < commandKeys.length; i++) {
                        if (Object.prototype.hasOwnProperty.call(rq, commandKeys[i])) {
                            commandName = commandKeys[i];
                            target = rq[commandName];
                            break;
                        }
                    }

                    if (typeof target === "string") {
                        ns = rq["$db"] + "." + target;
                    } else if (commandName) {
                        // Some commands target a database rather than a named
                        // collection (for example, a collectionless aggregate
                        // where "aggregate" is 1). Keep the database actionable
                        // and note the command type instead of dropping to
                        // "unknown".
                        ns = rq["$db"] + ".<" + commandName + ">";
                    }
                }
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
        var errors = [];
        var dbs;

        try {
            dbs = db.getMongo().getDBs();
        } catch (e) {
            // Surface a top-level failure (for example, insufficient privileges
            // to list databases) instead of aborting the script, so a JSON
            // report is still produced.
            errors.push({
                scope: "listDatabases",
                error: e.message
            });
            return { results: allResults, errors: errors };
        }

        if (!dbs.databases) {
            return { results: allResults, errors: errors };
        }

        dbs.databases.forEach(function (dbInfo) {
            var database = db.getSiblingDB(dbInfo.name);
            var collections;

            try {
                collections = getCollectionNames(database);
            } catch (e) {
                // Surface database-level failures (for example, due to
                // restricted privileges) rather than silently skipping them.
                errors.push({
                    db: dbInfo.name,
                    scope: "database",
                    error: e.message
                });
                return;
            }

            collections.forEach(function (collectionName) {
                var result = getCollectionIndexFilters(database, collectionName);

                if (result.error) {
                    // Surface collection-level failures so they are visible in
                    // the report instead of being filtered out.
                    errors.push({
                        db: result.db,
                        collection: result.collection,
                        namespace: result.namespace,
                        scope: "collection",
                        error: result.error
                    });
                    return;
                }

                if (result.hasIndexFilters) {
                    allResults.push(result);
                }
            });
        });

        return { results: allResults, errors: errors };
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
        print("  mongosh \"<connection-string>\" --quiet --eval 'var _mode=\"" + MODE_INDEX_FILTERS + "\"' get-planner-settings.js");
        print("  mongosh \"<connection-string>\" --quiet --eval 'var _mode=\"" + MODE_QUERY_SETTINGS + "\"' get-planner-settings.js");
        print("");
        print("Valid _mode values:");
        print("  " + MODE_INDEX_FILTERS);
        print("  " + MODE_QUERY_SETTINGS);
        quit(1);
    }

    if (_mode !== MODE_INDEX_FILTERS && _mode !== MODE_QUERY_SETTINGS) {
        print("Invalid _mode: " + _mode);
        printUsageAndExit();
    }

    if (_mode === MODE_INDEX_FILTERS) {
        var indexFilterResults = collectIndexFilters();

        printjson({
            generatedAt: new Date(),
            host: getHostInfo(),
            mode: _mode,
            summary: {
                collectionsWithIndexFilters: indexFilterResults.results.length,
                errorCount: indexFilterResults.errors.length
            },
            results: indexFilterResults.results,
            errors: indexFilterResults.errors
        });
        return;
    }

    var querySettingsResults = collectQuerySettings();

    if (querySettingsResults.error) {
        printjson({
            generatedAt: new Date(),
            host: getHostInfo(),
            mode: _mode,
            error: querySettingsResults.error,
            results: []
        });
        return;
    }

    printjson({
        generatedAt: new Date(),
        host: getHostInfo(),
        mode: _mode,
        summary: {
            namespacesWithQuerySettings: querySettingsResults.results.length,
            totalQuerySettingsReturned: querySettingsResults.totalQuerySettingsReturned
        },
        results: querySettingsResults.results
    });
}());
