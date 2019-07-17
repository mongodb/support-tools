/**
* Launch with `node processLite.js`
*/

var fs = require('fs');
var json = JSON.parse(fs.readFileSync('out.json', 'utf8'));

dbs = []
json.dbstats.forEach(function(element) {
  if (element.db != 'admin' && element.db != 'config') { // TODO: what about `local`?
      dbs.push(element.db);
  }
});
console.log(`DBs: ${dbs}`);
console.log(`DB Count: ${dbs.length}`);

collections = [] // collection names
// collection via DB and collection (and assert they are the same)
objectsViaDb = 0
bytesViaDb = 0 // data size
indexSizeTotal = 0
storageSizeTotal = 0

objectsViaColls = 0 // total objects in ALL databases/collections
bytesViaColls = 0

Object.keys(json.collstats).forEach(function(key) {
  if (key != 'admin'  && key != 'config') {
    collections.push(key);
    var elem = json.collstats[key];
    // collection via db.stats()
    objectsViaDb += elem.stats.objects;
    bytesViaDb += elem.stats.dataSize;
    indexSizeTotal += elem.stats.indexSize;
    storageSizeTotal += elem.stats.storageSize;
    // same for getCollectionNames
    elem.collections.forEach(function(coll){
      objectsViaColls += coll.count;
      bytesViaColls += coll.size;
    });
}
});

console.log(`objectsViaDb: ${objectsViaDb}`);
console.log(`objectsViaColls: ${objectsViaColls}`);
console.log(`bytesViaDb: ${bytesViaDb}`);
console.log(`bytesViaColls: ${bytesViaColls}`);
console.log(`indexSizeTotal: ${indexSizeTotal}`);
console.log(`storageSizeTotal: ${storageSizeTotal}`);
