/**
* Launch with `node processLite.js`
*/

var args = process.argv.slice(2);
var filename = args.length > 0 ? args[0] : 'out.json';

var fs = require('fs');
var json = JSON.parse(fs.readFileSync(filename, 'utf8'));

dbs = []
collections = [] // collection names
// collection via DB and collection (and assert they are the same)
objectsViaDb = 0
bytesViaDb = 0 // data size
indexSizeTotal = 0
storageSizeTotal = 0

objectsViaColls = 0 // total objects in ALL databases/collections
bytesViaColls = 0

Object.keys(json).forEach(function(key) {
  if (key != 'admin'  && key != 'config') {
    dbs.push(key);
    var elem = json[key];
    // collection via db.stats()
    objectsViaDb += elem.stats.objects;
    bytesViaDb += elem.stats.dataSize;
    indexSizeTotal += elem.stats.indexSize;
    storageSizeTotal += elem.stats.storageSize;
    // same for getCollectionNames
    elem.collections.forEach(function(coll){
      collections.push(coll.ns);
      objectsViaColls += coll.count;
      bytesViaColls += coll.size;
    });
}
});

console.log(`{`)
console.log(`\tdbs: "${dbs}",`);
console.log(`\tdbCount: ${dbs.length},`);
console.log(`\tcolls: "${collections}",`);
console.log(`\tcollCount: ${collections.length},`);
console.log(`\tobjectsViaDb: ${objectsViaDb},`);
console.log(`\tobjectsViaColls: ${objectsViaColls},`);
console.log(`\tbytesViaDb: ${bytesViaDb},`);
console.log(`\tbytesViaColls: ${bytesViaColls},`);
console.log(`\tindexSizeTotal: ${indexSizeTotal},`);
console.log(`\tstorageSizeTotal: ${storageSizeTotal},`);
console.log(`}`)
