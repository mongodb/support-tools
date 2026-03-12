# Database and Collection Size

This script lists all databases and collections (excluding system databases: `admin`, `config`, `local`) with their sizes in MB, sorted from largest to smallest.

## Usage

```bash
mongosh "mongodb://localhost:27017" --quiet collectionDatabaseSizes.js
```

Or with authentication:

```bash
mongosh "mongodb://user:password@localhost:27017" --quiet collectionDatabaseSizes.js
```

## Example Output

```
Database | Collection | Size (MB)
---------------------------------
mydb | largeCollection | 1024.50 MB
mydb | mediumCollection | 256.25 MB
otherdb | smallCollection | 12.00 MB
```

## Understanding Results

| Field | Description |
|-------|-------------|
| **Database** | Database name |
| **Collection** | Collection name |
| **Size (MB)** | Collection size in megabytes (sorted descending) |

### License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)

## DISCLAIMER
Please note: all tools/ scripts in this repo are released for use "AS IS" without any warranties of any kind, including, but not limited to their installation, use, or performance. We disclaim any and all warranties, either express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness for a particular purpose. We do not warrant that the technology will meet your requirements, that the operation thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is at your own risk. There is no guarantee that they have been through thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with their use.

You are responsible for reviewing and testing any scripts you run thoroughly before use in any non-testing environment.

Thanks,
The MongoDB Support Team
