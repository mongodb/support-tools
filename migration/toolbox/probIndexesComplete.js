const indexesUtilization = [];
const excludeDatabases = ['admin', 'config', 'local']
const byteToMB = (byte) => ((byte/1024)/1024).toFixed(2);

/* This version is used to get information on only a few DBs, add them to the following line*/
const databases = db.adminCommand('listDatabases').databases.filter(({ name }) => !excludeDatabases.includes(name))
const project = { $project: {'ops': "$accesses.ops", 'accesses.since': 1, 'name': 1, 'key': 1, 'spec': 1} };


for (const database of databases) {
	const currentDb = db.getSiblingDB(database.name)

	currentDb.getCollectionInfos({ type: "collection" }).forEach(function(collection){
        const currentCollection = currentDb.getCollection(collection.name);

        const indexes = currentCollection.getIndexes();
        const indexesSize = currentCollection.stats().indexSizes;

        currentCollection.aggregate( [ { $indexStats: { } }, project ] ).forEach(function(index){
            
            const indexDetail = indexes.find(i => i.name === index.name);
            const idxValues = Object.values(Object.assign({}, index.key));

            let indexType = "commom";
            if(index.name === '_id_') indexType = '[INTERNAL]';
            else if(idxValues.includes('2dsphere')) indexType = '2dsphere';
            else if(idxValues.includes("geoHaystack")) indexType = 'geoHaystack';
            else if(indexDetail?.textIndexVersion !== undefined) indexType = 'text';
            else if(indexDetail?.expireAfterSeconds !== undefined) indexType = 'TTL';
            else if(indexDetail?.partialFilterExpression !== undefined) indexType = 'Partial';
            
            indexesUtilization.push({
                db: database.name, 
                collection: collection.name, 
                name: index.name,
                type: indexType,
                unique: index.spec.unique,
                accesses: index.ops,
                'size (MB)': parseFloat(byteToMB(indexesSize[index.name])),
                size: indexesSize[index.name],
                accesses_since: index.accesses.since,
            })
        });
	})
}

//const indexesProblematic = indexesUtilization.filter(index => {return index.type === 'TTL'})
console.table(indexesUtilization);
//console.table(indexesProblematic);