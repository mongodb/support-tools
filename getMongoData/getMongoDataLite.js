print("================================");
print("DB Info");
print("================================");
db._adminCommand("listDatabases").databases.forEach(
    function (d) {
        mdb = db.getSiblingDB(d.name);
        printjson(mdb.stats());
});
print("================================");
print("Coll Info");
print("================================");
db.getMongo().getDBNames().forEach(function (name) {
    var mdb = db.getSiblingDB(name);
    print("\n\n\n======== DB: " + name + "========");
    printjson(mdb.stats());
    mdb.getCollectionNames().forEach(function(coll) {
        print("\nCollection: " + mdb.getCollection(coll));
        printjson(mdb.getCollection(coll).stats());
    });
});
