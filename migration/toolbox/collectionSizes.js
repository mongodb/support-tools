// List of system databases to exclude
const excludeDatabases = ['admin', 'config', 'local'];
const byteToMB = (byte) => ((byte / 1024) / 1024).toFixed(2);
const databaseInfo = [];

// Function to check if an array contains a value
const arrayContains = function(arr, val) {
    return arr.indexOf(val) !== -1;
};

// Get all databases and exclude system ones
const databases = db.adminCommand('listDatabases').databases.filter(function(database) {
    return !arrayContains(excludeDatabases, database.name);
});

// Debugging: Log the databases found
//print("Databases found (excluding system databases):");
//databases.forEach(function(database) {
//    print(" - " + database.name);
//});

for (var i = 0; i < databases.length; i++) {
    const database = databases[i];
    const currentDb = db.getSiblingDB(database.name);

    // Debugging: Log the current database being processed
    //print("Processing database: " + database.name);

    // Use getCollectionNames()
    const collections = currentDb.getCollectionNames();
    
    // Debugging: Log collections found in the database
    //print("Collections found in " + database.name + ":");
    //if (collections.length === 0) {
    //    print("  No collections found.");
    //}
    collections.forEach(function(collectionName) {
        //print("  - " + collectionName);
        const currentCollection = currentDb.getCollection(collectionName);
        const stats = currentCollection.stats(); // Get collection stats

        databaseInfo.push({
            db: database.name,
            collection: collectionName,
            size_MB: parseFloat(byteToMB(stats.size)), // Collection size in MB
            size: stats.size // Size in bytes
        });
    });
}

// Sort by size (descending order)
databaseInfo.sort(function(a, b) {
    return b.size - a.size;
});

// Print the sorted list of collections
print("Database | Collection | Size (MB)");
print("---------------------------------");
for (var j = 0; j < databaseInfo.length; j++) {
    const info = databaseInfo[j];
    print(info.db + " | " + info.collection + " | " + info.size_MB + " MB");
}