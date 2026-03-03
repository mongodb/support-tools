# Toolbox
Toolbox is a collection of helper scripts created by the Migration Factory team for data capture and analysis.

## [idChecker script](idCheker)

This script analyzes MongoDB collections for non-ObjectId _id types and insertion-order correlation patterns, predicting potential mongosync migration performance issues and providing optimization recommendations.

## Database and Collection size

**Script:** `collectionSizes.js`

Lists all databases and collections (excluding system databases: `admin`, `config`, `local`) with their sizes in MB, sorted from largest to smallest.

### Usage

```bash
mongosh "mongodb://localhost:27017" --quiet collectionSizes.js
```

Or with authentication:

```bash
mongosh "mongodb://user:password@localhost:27017" --quiet collectionSizes.js
```

### Example Output

```
Database | Collection | Size (MB)
---------------------------------
mydb | largeCollection | 1024.50 MB
mydb | mediumCollection | 256.25 MB
otherdb | smallCollection | 12.00 MB
```

## Index size, parameters and utilization

**Script:** `probIndexesComplete.js`

Collects index statistics across all user databases (excluding `admin`, `config`, `local`). For each index, it reports:
- Database and collection name
- Index name and type (common, TTL, Partial, text, 2dsphere, geoHaystack, or `[INTERNAL]` for `_id_`)
- Whether the index is unique
- Access count (ops) and when tracking started
- Index size in MB and bytes

### Usage

```bash
mongosh "mongodb://localhost:27017" --quiet probIndexesComplete.js
```

Or with authentication:

```bash
mongosh "mongodb://user:password@localhost:27017" --quiet probIndexesComplete.js
```

### Example Output

```
┌─────────┬────────┬────────────────┬──────────────┬────────────┬────────┬──────────┬──────────┬─────────┬─────────────────────────┐
│ (index) │ db     │ collection     │ name         │ type       │ unique │ accesses │ size (MB)│ size    │ accesses_since          │
├─────────┼────────┼────────────────┼──────────────┼────────────┼────────┼──────────┼──────────┼─────────┼─────────────────────────┤
│ 0       │ mydb   │ users          │ _id_         │ [INTERNAL] │        │ 150      │ 0.25     │ 262144  │ 2024-01-15T10:30:00.000Z│
│ 1       │ mydb   │ users          │ email_1      │ common     │ true   │ 1200     │ 0.12     │ 126976  │ 2024-01-15T10:30:00.000Z│
│ 2       │ mydb   │ sessions       │ _id_         │ [INTERNAL] │        │ 50       │ 0.08     │ 81920   │ 2024-01-15T10:30:00.000Z│
│ 3       │ mydb   │ sessions       │ expireAt_1   │ TTL        │        │ 0        │ 0.04     │ 40960   │ 2024-01-15T10:30:00.000Z│
└─────────┴────────┴────────────────┴──────────────┴────────────┴────────┴──────────┴──────────┴─────────┴─────────────────────────┘
```

## Mongosync Limitations Checker

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

For full documentation, filtering options, and examples, see [README_limitations_checker.md](README_limitations_checker.md).

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
