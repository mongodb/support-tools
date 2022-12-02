/**
* Launch with `node processLite.js` or `node processList.js <MYFILE.json>`
*/

var markdown = true; // include markdown summary table
var args = process.argv.slice(2);
var filename = args.length > 0 ? args[0] : 'out.json';

console.log(`Reading data from ${filename}`);

var fs = require('fs');
var content = fs.readFileSync(filename, 'utf8');

content = content.replace(/Timestamp\(.*\)/g, '1');
content = content.replace(/NumberLong\((.*)\)/g, '$1');
content = content.replace(/ObjectId\((.*)\)/g, '$1');

var json = JSON.parse(content);

dbs = [];
collections = []; // collection names
// collection via DB and collection (and assert they are the same)
objectsViaDb = 0;
bytesViaDb = 0; // data size
indexSizeTotal = 0;
storageSizeTotal = 0;

objectsViaColls = 0; // total objects in ALL databases/collections
bytesViaColls = 0;

if (markdown) {
  console.log(`| Database | dataSize | storageSize | indexSize |`);
  console.log(`| ---- | ---: | ---: | ----: |`);
}
Object.keys(json).forEach(function(key) {
  if (key != 'admin'  && key != 'config') {
    dbs.push(key);
    var elem = json[key];
    // collection via db.stats()
    objectsViaDb += elem.stats.objects;
    bytesViaDb += elem.stats.dataSize;
    // console.log(`dataSize ${key}: ${(elem.stats.dataSize/1024/1024/1024).toFixed(1)}GB`)
    indexSizeTotal += elem.stats.indexSize;
    // console.log(`indexSize ${key}: ${(elem.stats.indexSize/1024/1024/1024).toFixed(1)}GB`)
    storageSizeTotal += elem.stats.storageSize;
    // console.log(`storageSize ${key}: ${(elem.stats.storageSize/1024/1024/1024).toFixed(1)}GB`)
    if (markdown)
      console.log(`| ${key} | ${(elem.stats.dataSize/1024/1024/1024).toFixed(1)} | ${(elem.stats.storageSize/1024/1024/1024).toFixed(1)} | ${(elem.stats.indexSize/1024/1024/1024).toFixed(1)} | `)
    // same for getCollectionNames
    elem.collections.forEach(function(coll) {
      collections.push(coll.ns);
      objectsViaColls += coll.count;
      bytesViaColls += coll.size;
    });
}
});

console.log(`{\n` +
  `\tdbs: ${JSON.stringify(dbs)},\n`+
  `\tdbCount: ${dbs.length},\n`+
  `\tcolls: ${JSON.stringify(collections)},\n`+
  `\tcollCount: ${collections.length},\n`+
  `\tobjectsViaDb: ${objectsViaDb},\n`+
  `\tobjectsViaColls: ${objectsViaColls},\n`+
  `\tbytesViaDb: {\n`+
  `\t\traw: ${bytesViaDb},\n`+
  `\t\tgb: ${bytesViaDb/1024/1024/1024}\n`+
  `\t},\n` +
  `\tbytesViaColls: {\n`+
  `\t\traw: ${bytesViaColls},\n`+
  `\t\tgb: ${(bytesViaColls/1024/1024).toFixed(0)}\n`+
  `\t},\n` +
  `\tindexSizeTotal: {\n`+
  `\t\traw: ${indexSizeTotal},\n`+
  `\t\tgb: ${(bytesViaColls/1024/1024).toFixed(0)},\n`+
  `\t},\n` +
  `\tstorageSizeTotal: {\n`+
    `\t\traw: ${storageSizeTotal},\n`+
      `\t\tgb: ${(storageSizeTotal/1024/1024).toFixed(0)},\n`+
      `\t},\n` +
  `}`);
