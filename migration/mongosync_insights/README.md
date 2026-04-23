# Mongosync Insights

This tool can parse **mongosync** logs and metrics files, read the **mongosync** internal database (metadata), connect to the **mongosync** progress endpoint, and monitor the **migration-verifier** tool, generating interactive plots to assist with monitoring and troubleshooting ongoing MongoDB migrations.

## What Does This Tool Do?

Mongosync Insights provides five main capabilities:

1. **Log File Analysis**: Upload and parse mongosync log files to visualize migration progress, data transfer rates, performance metrics, configuration options, and detected errors
2. **Mongosync Metrics Analysis**: Upload and parse `mongosync_metrics.log` files to visualize 40+ mongosync metrics across Collection Copy, CEA, Indexes, Verifier, and more
3. **Live Monitoring**: Connect directly to the **mongosync** internal database or to the **mongosync** progress endpoint for real-time monitoring of ongoing migrations with auto-refreshing dashboards
4. **Combined Monitoring**: Provide both a MongoDB connection string and a progress endpoint URL to get a comprehensive view that merges metadata insights with real-time progress data
5. **Migration Verifier Monitoring**: Connect to the database where the [migration-verifier](https://github.com/mongodb-labs/migration-verifier) tool stores its metadata to track verification progress, generation history, and mismatch details

## Prerequisites

- **Python**: Version 3.11 or higher
- **pip**: Python package installer
- **MongoDB Access** (for live monitoring): Connection string to the destination cluster where **mongosync** stores its metadata
- **Progress Endpoint Access** (for live monitoring): Network access to the **mongosync** progress endpoint
- **Migration Verifier Access** (for verifier monitoring): Connection string to the cluster where the migration-verifier writes its metadata

## Installation

### Option A: RPM Installation (Air-Gapped / Offline Environments)

For machines without internet access, a self-contained RPM is available that bundles the Python runtime and all dependencies. No additional packages need to be installed on the target.

```bash
sudo rpm -i mongosync-insights-<version>.x86_64.rpm
sudo systemctl start mongosync-insights
```

See **[PACKAGING.md](PACKAGING.md)** for how to build the RPM, configure, and run the service.

### Option B: Manual Installation (Development / Connected Environments)

#### 1. Download the Tool

Download or clone the Mongosync Insights folder from this repository.

#### 2. Install Python Dependencies

Navigate to the directory containing the Python script and the `requirements.txt` file:

```bash
cd migration/mongosync_insights
```

Install the required Python packages:

```bash
pip3 install -r requirements.txt
```

**Note**: Run this in the Python environment where you want to use the tool. If using a virtual environment, activate it first.

## Running the Tool

### Start the Application

```bash
python3 mongosync_insights.py
```

The application will start and display:
```
Starting Mongosync Insights v0.8.1.14
Server: 127.0.0.1:3030
```

### Access the Web Interface

Open your web browser and navigate to:
```
http://localhost:3030
```

![Mongosync Logs Analyzer](images/mongosync_insights_home.png)

## Using Mongosync Insights

### Sidebar Navigation

Results pages include a left sidebar with quick-access buttons:

- **Upload** — opens a dialog listing saved analyses with **Load** and **Delete** actions, plus an **"Upload New File"** button to parse a new log file
- **Settings** — configure the live monitoring refresh interval, theme (Light, Dark, or System), and color scheme (MongoDB Green, Blue, Slate, Ocean)
- **Logout** — clears the current session and returns to the home page
- **Credits** — displays developer credits

### Option 1: Parsing Mongosync Log Files

1. Click the **"Browse"** or **"Choose File"** button
2. Select your mongosync log file from your file system
3. Click **"Open"** or **"Upload"**
4. The application will process the file and display results across multiple tabs

**Duplicate Upload Detection:** If you upload a file with the same name as an existing saved analysis, a dialog will appear offering three options: **Load Previous** (open the saved session without re-parsing), **Replace** (delete the saved session and parse the file again), or **Cancel**.

**Supported File Formats:**
- Plain text: `.log`, `.json`, `.out`
- Compressed: `.gz`, `.zip`, `.bz2`, `.tar.gz`, `.tgz`, `.tar.bz2`

Compressed files are automatically decompressed during processing. Archives (ZIP/TAR) containing multiple files are also supported -- each file inside is processed independently.

**Note**: Log files must be in mongosync's native **NDJSON** (Newline Delimited JSON) format. Each line should be a valid JSON object.

**Automatic File Classification:**

The tool automatically classifies files based on their filename:
- **Mongosync logs** (`mongosync.log`, `mongosync-*`, `liveimport_*`) -- parsed for migration progress and events
- **Mongosync metrics** (`mongosync_metrics.log`, `mongosync_metrics-*`) -- parsed for mongosync performance metrics

**Results Tabs:**

After upload, the results are organized into tabs:

| Tab | Description |
|-----|-------------|
| **Logs** | Migration progress plots: Total/Copied bytes, CEA Reads/Writes, Collection Copy Reads/Writes, Events applied, Lag Time |
| **Metrics** | Mongosync metrics plots (when a `mongosync_metrics` file is uploaded): 40+ metrics across Collection Copy, Core Replication, CEA Reader, CEA CRUD Applier, Hot Documents, Indexes, Buffer Service, Bulk Inserter, and Verifier |
| **Options** | Mongosync configuration options extracted from the logs (with **Copy as Markdown** for easy sharing) |
| **Collections** | Collection-level progress details (with **Copy as Markdown** for easy sharing) |
| **Errors** | Detected error patterns such as oplog rollover, timeouts, verifier mismatches, and write conflicts during cutover |
| **Log Viewer** | Browse recent log lines with severity filtering, semantic focus, multiple view modes (Highlighted, Raw, Pretty JSON, Summary), and full-text search across the entire log file |

![Mongosync Logs Tab](images/mongosync_logs_logs.png)
![Mongosync Metrics Tab](images/mongosync_logs_metrics.png)
![Mongosync Options Tab](images/mongosync_logs_options.png)
![Mongosync Collections and Partitions Tab](images/mongosync_logs_collections_partitions.png)
![Mongosync Errors and Warnings Tab](images/mongosync_logs_errors.png)
![Mongosync Log Viewer Tab](images/mongosync_logs_logviewer.png)

#### Analysis Snapshot Persistence

After parsing a log file, the analysis is automatically saved as a **snapshot** to disk. This allows you to reload a previous analysis instantly without re-parsing the original file.

- The home page displays a **"Previous Analyses"** section below the upload form, listing all saved snapshots with their filename, date, file size, and age
- Click **"Load"** to reopen a saved analysis — all tabs (plots, tables, log viewer) are restored immediately
- Click the **delete** button to remove a snapshot you no longer need
- Snapshots expire automatically after **24 hours** of inactivity; each time you load a snapshot, the TTL resets for another 24 hours
- By default, snapshots are stored in the system's temp directory. Use the `MI_LOG_STORE_DIR` environment variable to set a persistent storage location. See [CONFIGURATION.md](CONFIGURATION.md) for details

### Option 2: Live Monitoring (Metadata)

1. Enter the MongoDB **connection string** to your destination cluster
   - Format: `mongodb+srv://user:password@cluster.mongodb.net/`
   - This is where mongosync stores its internal metadata
2. Click **"Live Monitor"**
3. The page will refresh automatically every 10 seconds (configurable) showing:
   - State
   - Phase
   - Start and finish time
   - Lag time
   - Reversible
   - Write Blocking Mode
   - Build Indexes Method
   - Detect Random ID
   - Embedded Verifier method
   - Namespace Filters
   - Partitions Completed
   - Data Copied
   - Migration Phases
   - Collection Progress

![Mongosync metadata status](images/mongosync_metadata_status.png)
![Mongosync metadata progress](images/mongosync_metadata_progress.png)

### Option 3: Live Monitoring (Progress Endpoint)

1. Enter the MongoDB **Progress Endpoint URL**
   - Format: `host:port/api/v1/progress`
2. Click **"Live Monitor"**
3. The page will refresh automatically every 10 seconds (configurable) showing:
   - State
   - Lag time 
   - Can Commit
   - Can Write
   - Phase
   - Mongosync ID
   - Coordinator ID
   - Collection Copy progress
   - Direction Mapping (source x destination)
   - Source and Destination Ping Latency
   - Events applied
   - Verification table to compare the status between the source and the destination
   - Verification progress based on Document Count

![Mongosync Endpoint](images/mongosync_endpoint.png)

### Option 4: Combined Monitoring (Metadata + Progress Endpoint)

You can provide **both** the MongoDB connection string and the Progress Endpoint URL to get a comprehensive view that combines data from both sources. Simply fill in both fields and click **"Live Monitor"**.

This combined approach provides:
- Full metadata insights from the destination cluster (partitions, collection progress, configuration)
- Real-time progress data from the mongosync endpoint (state, lag time, verification status)

#### About the Embedded Verifier

The [Embedded Verifier](https://www.mongodb.com/docs/cluster-to-cluster-sync/current/reference/verification/embedded/) is mongosync's built-in verification mechanism, available since mongosync v1.9 and enabled by default. It performs document hashing on both source and destination clusters to confirm data was transferred correctly, without requiring any external tools.

**Embedded Verifier field (Status tab — Option 2):** The "Embedded Verifier" field displays the `verificationmode` value from mongosync's internal metadata. Possible values: `Enabled` (default — verification is active) or `Disabled` (verification was turned off at start).

**Can Write signal (Endpoint tab — Option 3):** `Can Write: True` is the definitive signal that the embedded verifier has completed successfully and found no mismatches. Until verification passes, `Can Write` remains `False`. This is the key field to watch for confirming migration correctness.

**Verification phases (Endpoint tab — Option 3):** The "Embedded Verifier Status" table shows a `Phase` field for both source and destination independently. Key phases include `stream hashing` (actively hashing documents from change streams) and `idle` (not yet started or between operations).

**Verifier Lag Time (Endpoint tab and uploaded metrics):** The `Lag Time Seconds` field in the verification table (and `Verifier Lag Time` in uploaded `mongosync_metrics.log` files) shows how far behind the verifier is in checking documents. High lag means verification will take longer to complete after commit. Persistently high lag may indicate the verifier cannot keep up with the write load.

### Option 5: Migration Verifier Monitoring

1. Enter the MongoDB **connection string** to the cluster where the [migration-verifier](https://github.com/mongodb-labs/migration-verifier) tool writes its metadata (typically the destination cluster)
2. Optionally customize the **Verifier Database Name** (default: `migration_verification_metadata`)
3. Click **"Monitor Verifier"**
4. The page will refresh automatically every 10 seconds (configurable) showing:
   - Generation history (Initial Verification, Recheck #1, #2, etc.)
   - Per-generation summary with task status (completed, failed, pending, processing)
   - Failed tasks details with mismatch information
   - Namespace stats (per-namespace verification progress)
   - Collection metadata mismatches

![Migration Verifier Dashboard](images/migration_verifier_dashboard.png)

#### Important: Embedded Verifier

> If verifying a migration done via mongosync, please check if the [Embedded Verifier](https://www.mongodb.com/docs/cluster-to-cluster-sync/current/reference/verification/embedded/) can be used, as it is the preferred approach for verification.

#### About Migration Verifier

The [migration-verifier](https://github.com/mongodb-labs/migration-verifier) is a standalone tool that validates migration correctness by comparing documents between source and destination clusters. It stores its state in a MongoDB database (default: `migration_verification_metadata`).

**How it works:** The verifier operates in two phases. First, an initial check (generation 0) partitions the source data into chunks and compares documents byte-by-byte between source and destination. Then, iterative rechecks (generation 1, 2, ...) re-verify any documents that changed or failed during previous rounds. Only the **last generation's failures** are significant — earlier failures may be transient due to ongoing writes.

**Key terms:**

| Term | Description |
|------|-------------|
| **Generation** | A round of verification. Generation 0 is the initial full check; subsequent generations are rechecks of changed/failed documents. |
| **FINAL** | Label shown on the dashboard for the last generation — only its failures indicate real mismatches. |
| **Task statuses** | `added` (unstarted), `processing` (in-progress), `completed` (no issues), `failed` (document mismatch), `mismatch` (collection metadata mismatch). |

**Metadata collections:**

| Collection | Purpose |
|------------|---------|
| `verification_tasks` | Tracks each verification task with a generation number, status, and type (`verify` for documents, `verifyCollection` for metadata). |
| `mismatches` | Records document-level mismatches found during verification. |

**Note**: The `MI_VERIFIER_CONNECTION_STRING` environment variable can be used to pre-configure the connection string. When omitted, it falls back to `MI_CONNECTION_STRING`. See **[CONFIGURATION.md](CONFIGURATION.md)** for details.

## Advanced Configuration

### Environment Variables

Configure the application using environment variables. See **[CONFIGURATION.md](CONFIGURATION.md)** for the complete reference, including:

- Server host and port settings
- MongoDB connection strings (live monitoring and migration verifier)
- Refresh intervals
- Upload size limits
- UI customization
- Custom error patterns file
- Security and session settings

**Quick Example:**
```bash
export MI_PORT=8080
export MI_REFRESH_TIME=5
export MI_CONNECTION_STRING="mongodb+srv://user:pass@cluster.mongodb.net/"
python3 mongosync_insights.py
```

### Security and HTTPS

For production deployments, enable HTTPS encryption. See **[HTTPS_SETUP.md](HTTPS_SETUP.md)** for:

- Quick Start with Let's Encrypt certificates
- Direct Flask SSL configuration
- Reverse proxy setup with Nginx/Apache (recommended)

**Quick Enable HTTPS:**
```bash
export MI_SSL_ENABLED=true
export MI_SSL_CERT=/path/to/certificate.pem
export MI_SSL_KEY=/path/to/private-key.pem
export MI_PORT=8443
python3 mongosync_insights.py
```

## Documentation

For detailed guides, see:

- **[PACKAGING.md](PACKAGING.md)** - Build a self-contained RPM for offline/air-gapped deployment
- **[CONFIGURATION.md](CONFIGURATION.md)** - Complete environment variables reference, configuration options, and MongoDB connection pooling
- **[HTTPS_SETUP.md](HTTPS_SETUP.md)** - Enable HTTPS/SSL for secure deployments
- **[VALIDATION.md](VALIDATION.md)** - Connection string validation, sanitization, and error handling

## Security Best Practices

- ✅ Always use HTTPS in production environments
- ✅ Keep SSL certificates up to date with auto-renewal
- ✅ Use environment variables for sensitive configuration (never hardcode connection strings)
- ✅ The application includes security headers for XSS, CSRF, and clickjacking protection
- ✅ Secure cookies are enabled by default when using HTTPS

## Troubleshooting

### Plots not visible after upload
- Refresh the page
- Check the console for error messages
- Verify the log file format is correct

### Connection failures (Live Monitoring)
- Verify the connection string format and credentials
- Ensure network connectivity to the MongoDB cluster
- Check that the mongosync internal database exists

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
