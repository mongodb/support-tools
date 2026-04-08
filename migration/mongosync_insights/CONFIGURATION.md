# Configuration Management Guide

This document explains the configuration management system for Mongosync Insights using environment variables.

## Prerequisites

**Python 3.11+** is required to run Mongosync Insights. See [README.md](README.md) for complete installation instructions.

## Configuration Overview

Mongosync Insights is configured entirely through **environment variables**. No configuration files are used.

### **Configuration Priority**

1. **Environment Variables** (highest priority)
2. **Default Values** (lowest priority)

All configuration can be set using `export` commands before running the application, or through your system's environment configuration.

## Environment Variables Reference

### Server Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_HOST` | `127.0.0.1` | Server host address (use `0.0.0.0` for all interfaces) |
| `MI_PORT` | `3030` | Server port number |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `MI_LOG_FILE` | `insights.log` | Path to log file |

### MongoDB Connection

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_CONNECTION_STRING` | _(empty)_ | MongoDB connection string (optional, can be provided via UI) |
| `MI_VERIFIER_CONNECTION_STRING` | _(falls back to `MI_CONNECTION_STRING`)_ | MongoDB connection string for the migration verifier database. When omitted, the value of `MI_CONNECTION_STRING` is used. Set this when the verifier database lives on a different cluster. |
| `MI_INTERNAL_DB_NAME` | _(auto-detected)_ | MongoDB internal database name. When not set, the app auto-detects between `__mdb_internal_mongosync` (new) and `mongosync_reserved_for_internal_use` (legacy). Set this variable to override auto-detection. |
| `MI_POOL_SIZE` | `10` | MongoDB connection pool size |
| `MI_TIMEOUT_MS` | `5000` | MongoDB connection timeout in milliseconds |

### Live Monitoring Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_REFRESH_TIME` | `10` | Live monitoring refresh interval in seconds |
| `MI_PROGRESS_ENDPOINT_URL` | _(empty)_ | Mongosync progress endpoint URL (optional, can be provided via UI) |

### File Upload Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_MAX_FILE_SIZE` | `10737418240` | Max upload file size in bytes (10GB) |

### Log Analysis Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_ERROR_PATTERNS_FILE` | `lib/error_patterns.json` _(auto-detected)_ | Path to a custom error patterns JSON file used during log analysis to detect common errors (e.g., oplog rollover, timeouts, verifier mismatches) |

### UI Customization

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_MAX_PARTITIONS_DISPLAY` | `10` | Maximum partitions to display in UI |

### Log Viewer & Snapshot Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_LOG_VIEWER_MAX_LINES` | `2000` | Maximum number of recent log lines shown in the Log Viewer tail view |
| `MI_LOG_STORE_DIR` | System temp directory | Directory for SQLite log stores and analysis snapshot files |
| `MI_LOG_STORE_MAX_AGE_HOURS` | `24` | TTL in hours for log store and snapshot files (based on last-access mtime) |

> **Note**: By default, log store databases and snapshot files are saved to the OS temp directory (e.g., `/tmp` on Linux/macOS), which may be cleared on system reboot. Set `MI_LOG_STORE_DIR` to a persistent path (e.g., `/data/mongosync-insights/store`) to retain snapshots across restarts. Files are cleaned up automatically on app startup, on logout, and lazily on access when they exceed the configured TTL. Loading a saved snapshot resets its TTL by touching the file's modification time.

### Security Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_SECURE_COOKIES` | `true` | Enable secure cookies (requires HTTPS) |
| `MI_SESSION_TIMEOUT` | `3600` | Session timeout in seconds (1 hour default) |
| `MI_SSL_ENABLED` | `false` | Enable HTTPS/SSL in Flask application |
| `MI_SSL_CERT` | `/etc/letsencrypt/live/your-domain/fullchain.pem` | Path to SSL certificate file |
| `MI_SSL_KEY` | `/etc/letsencrypt/live/your-domain/privkey.pem` | Path to SSL private key file |

> **Note**: Sessions are stored **in-memory** on the server. All active sessions are lost when the application restarts. This is by design to avoid persisting sensitive data (such as connection strings) to disk.

> **Note**: For detailed HTTPS setup instructions, see [HTTPS_SETUP.md](HTTPS_SETUP.md)
>

### Connection String Validation

> **Note**: For connection string handling information, see [VALIDATION.md](VALIDATION.md)

---

## Usage Examples

### Example 1: Basic Local Development

Default settings - no environment variables needed:

```bash
# Run with all defaults
python3 mongosync_insights.py

# Access at: http://127.0.0.1:3030
```

### Example 2: Custom Port and Host

Run on a different port and allow external connections:

```bash
# Set custom port and host
export MI_PORT=8080
export MI_HOST=0.0.0.0

# Run the application
python3 mongosync_insights.py

# Access at: http://your-ip:8080
```

### Example 3: Pre-configured MongoDB Connection

Set the MongoDB connection string to avoid entering it in the UI:

```bash
# Set connection string
export MI_CONNECTION_STRING="mongodb+srv://user:pass@cluster.mongodb.net/"

# Optional: Adjust refresh rate
export MI_REFRESH_TIME=5

# Run the application
python3 mongosync_insights.py
```

### Example 3b: Combined Monitoring (Metadata + Progress Endpoint)

Pre-configure both the connection string and progress endpoint for comprehensive monitoring:

```bash
# Set MongoDB connection string for metadata access
export MI_CONNECTION_STRING="mongodb+srv://user:pass@cluster.mongodb.net/"

# Set mongosync progress endpoint URL
export MI_PROGRESS_ENDPOINT_URL="localhost:27182/api/v1/progress"

# Faster refresh for active migrations
export MI_REFRESH_TIME=5

# Run the application
python3 mongosync_insights.py
```

### Example 4: Debug Mode with Logging

Enable detailed logging for troubleshooting:

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
export MI_LOG_FILE=/var/log/mongosync-insights/debug.log

# Run the application
python3 mongosync_insights.py

# Tail the log in another terminal
tail -f /var/log/mongosync-insights/debug.log
```

### Example 5: Production Configuration with HTTPS

Secure production setup with HTTPS:

```bash
# Server configuration
export MI_HOST=127.0.0.1  # Behind reverse proxy
export MI_PORT=3030
export LOG_LEVEL=INFO

# Security settings
export MI_SSL_ENABLED=false  # Nginx handles SSL
export MI_SECURE_COOKIES=true

# MongoDB connection
export MI_CONNECTION_STRING="mongodb+srv://user:pass@production-cluster.mongodb.net/"

# Performance settings
export MI_POOL_SIZE=20
export MI_TIMEOUT_MS=10000

# Run the application
python3 mongosync_insights.py
```

See [HTTPS_SETUP.md](HTTPS_SETUP.md) for complete production deployment guide.

### Example 6: Custom Upload Size and UI Settings

Adjust file upload limits and plot dimensions:

```bash
# Allow larger log files (20GB)
export MI_MAX_FILE_SIZE=21474836480

# Customize UI settings
export MI_MAX_PARTITIONS_DISPLAY=20

# Run the application
python3 mongosync_insights.py
```

### Example 7: Migration Verifier Monitoring

Pre-configure the connection string for the [migration-verifier](https://github.com/mongodb-labs/migration-verifier) database:

```bash
# Set verifier connection string (separate cluster from live monitoring)
export MI_VERIFIER_CONNECTION_STRING="mongodb+srv://user:pass@verifier-cluster.mongodb.net/"

# Or reuse the same connection string as live monitoring
export MI_CONNECTION_STRING="mongodb+srv://user:pass@cluster.mongodb.net/"

# Run the application
python3 mongosync_insights.py
```

**Note**: When `MI_VERIFIER_CONNECTION_STRING` is not set, it falls back to `MI_CONNECTION_STRING`. Set it explicitly when the migration-verifier writes to a different cluster.

### Example 8: Persistent Snapshots and Custom Log Viewer

Configure snapshot storage location, retention period, and log viewer buffer size:

```bash
# Store snapshots in a persistent directory
export MI_LOG_STORE_DIR=/data/mongosync-insights/store

# Keep snapshots for 48 hours instead of the default 24
export MI_LOG_STORE_MAX_AGE_HOURS=48

# Show up to 5000 recent log lines in the Log Viewer tail view
export MI_LOG_VIEWER_MAX_LINES=5000

# Run the application
python3 mongosync_insights.py
```

---

## Troubleshooting

### Environment Variables Not Taking Effect

**Problem**: Changed environment variables but application uses defaults

**Solution**: 
```bash
# Verify variables are set
env | grep MI_

# Use -E flag with sudo to preserve environment
sudo -E python3 mongosync_insights.py
```

### Connection String Not Working

**Problem**: `MI_CONNECTION_STRING` is set but application still asks for it

**Solution**: 
- Verify the connection string format: `mongodb+srv://user:pass@cluster.mongodb.net/`
- Check for extra quotes or spaces
- Test connection string with `mongosh` first

### Log File Permission Denied

**Problem**: Cannot write to log file location

**Solution**:
```bash
# Use writable location
export MI_LOG_FILE=$HOME/mongosync-insights.log

# Or create directory with proper permissions
sudo mkdir -p /var/log/mongosync-insights
sudo chown $USER:$USER /var/log/mongosync-insights
export MI_LOG_FILE=/var/log/mongosync-insights/insights.log
```

---

## Related Documentation

- **[README.md](README.md)** - Getting started and installation guide
- **[HTTPS_SETUP.md](HTTPS_SETUP.md)** - Enable HTTPS/SSL for secure deployments
- **[VALIDATION.md](VALIDATION.md)** - Connection string validation, sanitization, and error handling

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