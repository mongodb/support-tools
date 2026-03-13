# Mongosync Insights

This tool can parse **mongosync** logs and metrics files, read the **mongosync** internal database (metadata), connect to the **mongosync** progress endpoint, and monitor the **migration-verifier** tool, generating interactive plots to assist with monitoring and troubleshooting ongoing MongoDB migrations.

## What Does This Tool Do?

Mongosync Insights provides four main capabilities:

1. **Log File Analysis**: Upload and parse mongosync log files to visualize migration progress, data transfer rates, performance metrics, configuration options, and detected errors
2. **Mongosync Metrics Analysis**: Upload and parse `mongosync_metrics.log` files to visualize 40+ mongosync metrics across Collection Copy, CEA, Indexes, Verifier, and more
3. **Live Monitoring**: Connect directly to the **mongosync** internal database or to the **mongosync** progress endpoint for real-time monitoring of ongoing migrations with auto-refreshing dashboards
4. **Migration Verifier Monitoring**: Connect to the database where the [migration-verifier](https://github.com/mongodb-labs/migration-verifier) tool stores its metadata to track verification progress, generation history, and mismatch details

## Prerequisites

- **Python**: Version 3.11 or higher
- **pip**: Python package installer
- **MongoDB Access** (for live monitoring): Connection string to the destination cluster where **mongosync** stores its metadata
- **Progress Endpoint Access** (for live monitoring): Network access to the **mongosync** progress endpoint
- **Migration Verifier Access** (for verifier monitoring): Connection string to the cluster where the migration-verifier writes its metadata

## Installation

### 1. Download the Tool

Download or clone the Mongosync Insights folder from this repository.

### 2. Install System Dependencies

Before installing Python packages, ensure **libmagic** is installed on your system (required for file type detection):

**macOS:**
```bash
brew install libmagic
```

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install libmagic1
```

**Red Hat/CentOS/Fedora:**
```bash
sudo yum install file-libs
```

**Windows:**
- Download and install from [https://github.com/nscaife/file-windows](https://github.com/nscaife/file-windows)
- Or use: `pip install python-magic-bin` (includes precompiled libmagic)

### 3. Install Python Dependencies

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
Starting Mongosync Insights v0.8.0.18
Server: 127.0.0.1:3030
```

### Access the Web Interface

Open your web browser and navigate to:
```
http://localhost:3030
```

![Mongosync Logs Analyzer](images/mongosync_insights_home.png)

## Using Mongosync Insights

### Option 1: Parsing Mongosync Log Files

1. Click the **"Browse"** or **"Choose File"** button
2. Select your mongosync log file from your file system
3. Click **"Open"** or **"Upload"**
4. The application will process the file and display results across multiple tabs

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

![Mongosync Logs Tab](images/mongosync_logs_logs.png)
![Mongosync Metrics Tab](images/mongosync_logs_metrics.png)
![Mongosync Options Tab](images/mongosync_logs_options.png)
![Mongosync Collections and Partitions Tab](images/mongosync_logs_collections_partitions.png)
![Mongosync Errors and Warnings Tab](images/mongosync_logs_errors.png)

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
