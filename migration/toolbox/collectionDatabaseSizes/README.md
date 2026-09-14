# Database and Collection Size

This script lists collections in all databases except `admin`, `config`, and `local`, and reports MongoDB collection statistics, including logical data size and WiredTiger storage allocation details. Results are sorted by logical data size from largest to smallest.

## Usage

```bash
mongosh "mongodb://localhost:27017" --quiet collectionDatabaseSizes.js
```

Or with authentication:

```bash
mongosh "mongodb://user:password@localhost:27017" --quiet collectionDatabaseSizes.js
```

## Options and behavior

The script currently supports the following runtime behavior:

- It always runs with a primary read preference. This is intentional: the script scans database and collection metadata across many namespaces and is not safe for secondary reads.
- Output format is controlled by the `OUTPUT_FORMAT` environment variable.
  - Default: `table`
  - Supported values: `table`, `json`, `csv`

Examples:

```bash
OUTPUT_FORMAT=csv mongosh "mongodb://localhost:27017" --quiet collectionDatabaseSizes.js
OUTPUT_FORMAT=json mongosh "mongodb://localhost:27017" --quiet collectionDatabaseSizes.js
```

There are currently no CLI flags for selecting read preference or output format; the supported switch is the environment variable above.

## Example Output

```text
Database | Collection | Docs | Avg Doc (KB) | Data (MB) | Stor (MB) | Total Idx | Unique Idx | Idx Size (MB) | Reuse Doc (MB) | Capped | Clustered | Time | TTL | Compressor | Sharded | Shard Key
------------------------------------------------------------------------------------------------------------------------------------------------------
mydb | largeCollection | 123456 | 1.2 | 2048 | 1024.5 | 4 | 1 | 128 | 64.25 | false | false | false | false | snappy | true | {"customerId":1}
mydb | mediumCollection | 45678 | 0.8 | 512 | 256.25 | 2 | 0 | 32 | 10.5 | false | false | false | false | snappy | false | N/A
otherdb | smallCollection | 320 | 0.25 | 12 | 4.5 | 1 | 0 | 1 | 0 | false | false | false | false | N/A | false | N/A
```

## Understanding Results

| Field | Description |
|-------|-------------|
| **Database** | Database name |
| **Collection** | Collection name |
| **Documents** | Number of documents in the collection (`stats.count`) |
| **Avg Doc Size (KB)** | Average document size (`stats.avgObjSize`), reported in kilobytes |
| **Data Size (MB)** | Logical BSON data size (`stats.size`) |
| **Storage Size (MB)** | Allocated on-disk document storage (`stats.storageSize`); reflects WiredTiger allocation and compression behavior |
| **Total Indexes** | Total number of indexes in the collection, including the default `_id_` index (`stats.nindexes`) |
| **Unique Indexes** | Number of indexes with `unique: true`; does not include the default `_id_` index unless it is explicitly reported as unique by MongoDB |
| **Total Index Size (MB)** | Total size of all indexes (`stats.totalIndexSize`) |
| **Reusable Doc Storage (MB)** | Allocated collection storage that WiredTiger can reuse (`stats.freeStorageSize`), with a WiredTiger reusable-block fallback when the field is omitted |
| **Compressor** | Best-effort WiredTiger collection compressor (`snappy`, `zlib`, `zstd`, or `none`) from collection metadata; `N/A` when unavailable |
| **Capped / Clustered / Time-Series / Has TTL Index / Sharded** | Collection metadata and index properties |
| **Shard Key** | Shard key pattern from `config.collections` when the collection is sharded and metadata is available; otherwise `N/A` |

## Table column name legend

The terminal table uses compact labels to keep columns readable without making the output too wide. The following names are the short form used in the table output and the full meaning behind them:

| Short name | Full meaning |
|------------|--------------|
| **Database** | Database name |
| **Collection** | Collection name |
| **Docs** | Number of documents in the collection (`stats.count`) |
| **Avg Doc (KB)** | Average document size in kilobytes (`stats.avgObjSize` / 1024) |
| **Data (MB)** | Logical BSON data size (`stats.size`), shown in MB |
| **Stor (MB)** | Allocated on-disk document storage (`stats.storageSize`), shown in MB |
| **Total Idx** | Total number of indexes on the collection, including the default `_id_` index (`stats.nindexes`) |
| **Unique Idx** | Number of indexes with `unique: true` |
| **Idx Size (MB)** | Total index size (`stats.totalIndexSize`), shown in MB |
| **Reuse Doc (MB)** | Allocated collection storage that WiredTiger can reuse (`stats.freeStorageSize`), shown in MB. MongoDB omits `freeStorageSize` when it is zero; the script falls back to WiredTiger's reusable-block counter when available, so `0` means no reusable space and `N/A` means the metric is unavailable. It is not filesystem free space. |
| **Capped** | Whether the collection is capped |
| **Clustered** | Whether the collection uses a clustered index |
| **Time** | Whether the collection is a time-series collection |
| **TTL** | Whether the collection has at least one TTL index |
| **Compressor** | Best-effort WiredTiger collection compressor (`snappy`, `zlib`, `zstd`, or `none`) from collection metadata |
| **Sharded** | Whether the collection is sharded, when that information is available from MongoDB |
| **Shard Key** | Shard key pattern for sharded collections, when available from `config.collections` |

## Important note on semantics

These values are MongoDB internal WiredTiger allocation metrics. They are not OS or filesystem free-space measurements.

- `stats.size` and `stats.storageSize` describe MongoDB-managed logical and allocated storage.
- `stats.freeStorageSize` describes unused space inside collection allocation units that MongoDB may reuse.
- They do not represent free space on the underlying disk, nor the remaining capacity of the mounted filesystem.
- A collection reporting `Data (MB) = 36`, `Stor (MB) = 107`, and `Reuse Doc (MB) = 36` has 36 MB of logical BSON data, 107 MB of allocated collection storage, and 36 MB of that allocation available for future writes. The remaining difference reflects compressed storage, internal metadata, page layout, and non-reusable allocation; these values are not expected to add up directly.
- Deletes do not necessarily create reusable WiredTiger blocks. `Reuse Doc (MB)` may be `0` after a delete when WiredTiger can shrink or reorganize the affected allocation instead; `N/A` means neither the `collStats` field nor the WiredTiger fallback was available.

## License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)

## DISCLAIMER
Please note: all tools/ scripts in this repo are released for use "AS IS" without any warranties of any kind, including, but not limited to their installation, use, or performance. We disclaim any and all warranties, either express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness for a particular purpose. We do not warrant that the technology will meet your requirements, that the operation thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is at your own risk. There is no guarantee that they have been through thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with their use.

You are responsible for reviewing and testing any scripts you run thoroughly before use in any non-testing environment.

Thanks,
The MongoDB Support Team
