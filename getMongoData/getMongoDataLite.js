//
// Launch like:
// mongo --quiet < getMongoDataLite.js > out.json
//

print("{");
db.getMongo().getDBNames().forEach(function (name, idx, array) {
    var mdb = db.getSiblingDB(name);
    print("\"" + name + "\": { \n\t\t\"stats\":");
    printjson(mdb.stats());
    print("\n\t, \"collections\": [")
    mdb.getCollectionNames().forEach(function(coll, idx2, array2) {
        printjson(mdb.getCollection(coll).stats());
        if (idx2 < array2.length - 1) print(",");
    });
    print("\t]\n}")
    if (idx < array.length - 1) print(",");
});
print("\n}");
