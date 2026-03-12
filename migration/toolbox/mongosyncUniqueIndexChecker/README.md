# Mongosync Limitations Checker (Unified)

This script detects a known **mongosync limitation**:

> A collection that has two indexes with the exact same key pattern where one is **unique** and the other is **non-unique**.

This condition can cause mongosync to fail or behave unexpectedly during migrations.  
The script is intended as a **pre-check** for MRAs and migration readiness reviews.

---

## What the script does

For every collection it scans, the script:

1. Retrieves all index definitions.
2. Separates them into:
   - **unique** indexes
   - **non-unique** indexes
3. Compares index key patterns.
4. Flags a limitation when it finds the *same key pattern* in both groups.

### Output

- Prints a clean terminal report.
- Optionally writes a JSON report using `--out`.

Each finding includes:
- `database`
- `collection`
- `index_keys`
- `unique_index_names`
- `non_unique_index_names`

**Sample terminal output:**

```
Starting mongosync limitations checker (ONLINE).
Input: mongodb+srv://...
Limitations found: 1

- mydb.users | keys={['email', 1]} | uniqueIndex=['email_unique_idx'] | non-uniqueIndex=['email_idx']

Finishing mongosync limitations checker.
```

**Sample JSON output** (when using `--out`):

```json
[
  {
    "database": "mydb",
    "collection": "users",
    "index_keys": [["email", 1]],
    "unique_index_names": ["email_unique_idx"],
    "non_unique_index_names": ["email_idx"]
  }
]
```

---

## What it runs against

The script supports **two modes**.

### Online mode (MongoDB cluster)

Reads indexes directly from a MongoDB deployment using a connection string.

Supported:
- MongoDB Atlas clusters
- Self-managed replica sets / Sharded clusters

### Offline mode (getMongoData JSON)

Runs without cluster access by parsing a `getMongoData` output JSON.

---

## Requirements

### Offline mode
- Python 3.7+
- No external dependencies

### Online mode
- Python 3.7+
- PyMongo:
```bash
python3 -m pip install pymongo
```

---

## Atlas / SRV TLS note

PyMongo uses the Python/OS trust store. On some machines you may need `certifi`:
```bash
python3 -m pip install certifi
```
Run the script with `--use-certifi-ca` when connecting to Atlas.

---

## Usage

Exactly one mode flag is required.
```bash
python3 mongosync_uniqueindex_limitation_checker.py \
(--uri "<MONGODB_URI>" | --getmongodata <getMongoData.json>) \
[flags...]
```

---

## Flags

**Mode selection (required)**

| Flag             | Description                               |
| ---------------- | ----------------------------------------- |
| `--uri`          | Online mode. Connect to a MongoDB cluster |
| `--getmongodata` | Offline mode. Parse getMongoData JSON     |

---

**Filters (apply to both modes)**

| Flag            | Description                      |
| --------------- | -------------------------------- |
| `--include-dbs` | Comma-separated DB allow-list    |
| `--exclude-dbs` | Comma-separated DB block-list    |
| `--include-ns`  | Regex applied to `db.collection` |

---

**Output**

| Flag    | Description                   |
| ------- | ----------------------------- |
| `--out` | Write findings to a JSON file |

---

**TLS helper (online only)**

| Flag               | Description                                    |
| ------------------ | ---------------------------------------------- |
| `--use-certifi-ca` | Use certifi CA bundle (fixes Atlas TLS issues) |

---

## How to use the filters

**Include / exclude DBs**

```bash
--include-dbs prod_01,prod_02
--exclude-dbs test,staging
```
- System DBs (`admin`, `local`, `config`) are always skipped.

**Namespace regex filter**

The `--include-ns` flag accepts a regex pattern that is searched against the full namespace (`db.collection`):

```bash
--include-ns "^prod_"         # Namespaces starting with "prod_"
--include-ns "\.users$"       # Collections ending with "users"
--include-ns "orders"         # Namespaces containing "orders"
```

---

## Examples

### Offline (getMongoData)

```bash
python3 mongosync_uniqueindex_limitation_checker.py \
--getmongodata <getMongoData_output>.json
```

With JSON output:

```bash
python3 mongosync_uniqueindex_limitation_checker.py \
--getmongodata <getMongoData_output>.json \
--out <output_file>.json
```

Offline + DB filter:

```bash
python3 mongosync_uniqueindex_limitation_checker.py \
--getmongodata <getMongoData_output>.json \
--include-dbs <db1>,<db2> \
--out <output_file>.json
```

---

### Online (non-SRV)

```bash
python3 mongosync_uniqueindex_limitation_checker.py \
--uri "mongodb://<username>:<password>@<host>:<port>/admin?appName=<app_name>" \
--out <output_file>.json
```

---

### Online (Atlas SRV)

```bash
python3 mongosync_uniqueindex_limitation_checker.py \
--uri "mongodb+srv://USER:PASS@<SRV_conn_String>/admin?appName=checker" \
--out <output_file>.json
```

If you see TLS errors:

```bash
python3 -m pip install certifi
```

Then: 

```bash
python3 mongosync_uniqueindex_limitation_checker.py \
--uri "mongodb+srv://USER:PASS@<SRV_conn_String>/admin?appName=checker" \
--use-certifi-ca \
--out <output_file>.json
```

---

## Notes

- The script is read-only.
- Permission errors on specific collections are skipped.

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