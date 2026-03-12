# Toolbox
Toolbox is a collection of helper scripts created by the Migration Factory team for data capture and analysis.

## [idChecker script](idChecker)

This script analyzes MongoDB collections for non-ObjectId _id types and insertion-order correlation patterns, predicting potential mongosync migration performance issues and providing optimization recommendations.

## [Database and Collection size](collectionDatabaseSizes)

Lists all databases and collections (excluding system databases: `admin`, `config`, `local`) with their sizes in MB, sorted from largest to smallest. For full documentation and examples, see [collectionDatabaseSizes README](collectionDatabaseSizes/README.md).

## [Index size, parameters and utilization](probIndexesComplete)

Collects index statistics across all user databases (excluding `admin`, `config`, `local`), reporting index name, type, uniqueness, access count, and size for each index. For full documentation and examples, see [probIndexesComplete README](probIndexesComplete/README.md).

## (Mongosync Unique Index Limitations Checker)[mongosyncUniqueIndexChecker]

**Script:** `mongosync_uniqueindex_limitation_checker.py`

Detects a known mongosync limitation where a collection has two indexes with the exact same key pattern—one unique and one non-unique. This condition can cause mongosync to fail during migrations.

The script supports two modes:
- **Online mode:** Connects directly to a MongoDB cluster via connection string
- **Offline mode:** Parses a `getMongoData` JSON file (no cluster access required)

### Quick Usage

**Offline (getMongoData):**
```bash
python3 mongosync_uniqueindex_limitation_checker.py --getmongodata <file>.json
```

**Online (MongoDB cluster):**
```bash
python3 mongosync_uniqueindex_limitation_checker.py --uri "mongodb+srv://USER:PASS@host"
```

For full documentation, filtering options, and examples, see [Mongosync Unique Index Limitations Checker README](mongosyncUniqueIndexChecker/README.md).

### License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)

DISCLAIMER
----------
Please note: all tools/ scripts in this repo are released for use "AS IS" **without any warranties of any kind**,
including, but not limited to their installation, use, or performance.  We disclaim any and all warranties, either 
express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness 
for a particular purpose.  We do not warrant that the technology will meet your requirements, that the operation 
thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is **at your own risk**.  There is no guarantee that they have been through 
thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with 
their use.

You are responsible for reviewing and testing any scripts you run *thoroughly* before use in any non-testing 
environment.

Thanks,  
The MongoDB Support Team
