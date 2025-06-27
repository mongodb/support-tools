# README

This directory contains a script to help you determine if you're affected by the critical advisory detailed in [SERVER-86622](https://jira.mongodb.org/browse/SERVER-86622) and to fix any issues found. Please read the Important Instructions below before running the script. The script uses the following syntax:

```
mongosh <connection_string> <script.js> [<dbName> <collName> [fix]]
```

- `<dbName>`: The name of the database.
- `<collName>`: The name of the collection.

**Note:** Keep the order of arguments as shown above. Any additional arguments for authentication or other purposes should be added at the end.

### Usage

- **Check for inconsistencies across all sharded collections:**

  ```
  mongosh <connection_string> <script.js>
  ```

- **Check if a specific collection is affected:**

  ```
  mongosh <connection_string> <script.js> <dbName> <collName>
  ```

- **Fix an inconsistency in a specific collection:**

  ```
  mongosh <connection_string> <script.js> <dbName> <collName> fix
  ```

The script will display progress updates as it runs.

### How the Script Works

To fix the issue, the script creates an infinitesimal chunk from an existing chunk in the collection with a random UUID and moves it to the current primary shard of the affected database, then back to its original shard. This process helps create a missing collection catalog entry in the primary shard's local catalog.

## Important Instructions

1. Ensure your user has the `atlasAdmin` or an equivalent role to execute the script.
2. Run the script from an empty directory against a **mongos** instance. You might see an error like:
   ```
   Error: ENOENT: no such file or directory, open '<CURRENT_WORKING_DIRECTORY>/<dbName>'
   ```
   This occurs because `mongosh` tries to find a file named `<dbName>` in the current directory. Currently, there's no way to pass direct arguments to a `mongosh` script without `mongosh` interpreting them.
3. Disable the balancer with `sh.stopBalancer()` before running the script to fix any inconsistencies. The `moveChunk` operation in the script can conflict with ongoing chunk migrations. Re-enable the balancer after the script completes.
4. If inconsistencies are found across all collections, double-check by specifying `<dbName>` and `<collName>` before fixing, as temporary states may occur due to background operations.
5. Avoid starting any DDL operations like `movePrimary` or `reshardCollection` on the inconsistent collection/database before running the script.
