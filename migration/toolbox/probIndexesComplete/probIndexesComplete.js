const fs = require('fs');

const indexesUtilization = [];
const excludeDatabases = ['admin', 'config', 'local'];
const byteToMB = (byte) => ((byte / 1024) / 1024).toFixed(2);

const csvOutputFile = 'probIndexesComplete.csv';
const mdOutputFile = 'probIndexesComplete.md';

/* This gets information for all non-system DBs. To limit it to specific DBs, edit the filter in the next line (e.g., by adding an explicit include list). */
const databases = db.adminCommand('listDatabases').databases.filter(({ name }) => !excludeDatabases.includes(name));

const project = {
  $project: {
    ops: "$accesses.ops",
    "accesses.since": 1,
    name: 1,
    key: 1,
    spec: 1
  }
};

function stringifyValue(value) {
  if (value === undefined) return '';
  if (value === null) return '';
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch (e) {
      return String(value);
    }
  }
  return String(value);
}

function escapeCsv(value) {
  const str = stringifyValue(value);
  return `"${str.replace(/"/g, '""')}"`;
}

function escapeMarkdown(value) {
  const str = stringifyValue(value);
  return str.replace(/\|/g, '\\|').replace(/\n/g, '<br>');
}

for (const database of databases) {
  const currentDb = db.getSiblingDB(database.name);

  currentDb.getCollectionInfos({ type: "collection" }).forEach(function (collection) {
    const currentCollection = currentDb.getCollection(collection.name);

    const indexes = currentCollection.getIndexes();
    const indexesSize = currentCollection.stats().indexSizes;

    currentCollection.aggregate([{ $indexStats: {} }, project]).forEach(function (index) {
      const indexDetail = indexes.find(i => i.name === index.name);
      const idxValues = Object.values(Object.assign({}, index.key));

      let indexType = "common";
      if (index.name === '_id_') indexType = '[INTERNAL]';
      else if (idxValues.includes('2dsphere')) indexType = '2dsphere';
      else if (idxValues.includes('geoHaystack')) indexType = 'geoHaystack';
      else if (indexDetail?.textIndexVersion !== undefined) indexType = 'text';
      else if (indexDetail?.expireAfterSeconds !== undefined) indexType = 'TTL';
      else if (indexDetail?.partialFilterExpression !== undefined) indexType = 'Partial';

      indexesUtilization.push({
        db: database.name,
        collection: collection.name,
        name: index.name,
        indexKeyPattern: index.key,
        type: indexType,
        unique: index.spec?.unique,
        'size (MB)': parseFloat(byteToMB(indexesSize[index.name])),
        size: indexesSize[index.name],
        accesses: index.ops,
        accesses_since: index.accesses.since
      });
    });
  });
}

function writeCsv(data, fileName) {
  if (!data.length) {
    fs.writeFileSync(fileName, 'No data found\n', 'utf8');
    return;
  }

  const headers = Object.keys(data[0]);
  const lines = [
    headers.map(escapeCsv).join(',')
  ];

  data.forEach(row => {
    lines.push(headers.map(header => escapeCsv(row[header])).join(','));
  });

  fs.writeFileSync(fileName, lines.join('\n'), 'utf8');
}

function writeMarkdown(data, fileName) {
  if (!data.length) {
    fs.writeFileSync(fileName, '# Index Utilization Report\n\nNo data found.\n', 'utf8');
    return;
  }

  const headers = Object.keys(data[0]);

  const mdLines = [];
  mdLines.push('# Index Utilization Report');
  mdLines.push('');
  mdLines.push(`Generated at: ${new Date().toISOString()}`);
  mdLines.push('');
  mdLines.push(`Total indexes: ${data.length}`);
  mdLines.push('');
  mdLines.push(`| ${headers.map(escapeMarkdown).join(' | ')} |`);
  mdLines.push(`| ${headers.map(() => '---').join(' | ')} |`);

  data.forEach(row => {
    mdLines.push(`| ${headers.map(header => escapeMarkdown(row[header])).join(' | ')} |`);
  });

  mdLines.push('');

  fs.writeFileSync(fileName, mdLines.join('\n'), 'utf8');
}

writeCsv(indexesUtilization, csvOutputFile);
writeMarkdown(indexesUtilization, mdOutputFile);

print(`CSV output written to: ${csvOutputFile}`);
print(`Markdown output written to: ${mdOutputFile}`);
print(`Total indexes exported: ${indexesUtilization.length}`);