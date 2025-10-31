# Configuration Management Guide

This document explains the configuration management system for Mongosync Insights using environment variables.

## Prerequisites

**Python 3.10+** is required to run Mongosync Insights. See [README.md](README.md) for installation instructions.

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
| `MI_INTERNAL_DB_NAME` | `mongosync_reserved_for_internal_use` | MongoDB internal database name |
| `MI_POOL_SIZE` | `10` | MongoDB connection pool size |
| `MI_TIMEOUT_MS` | `5000` | MongoDB connection timeout in milliseconds |

### Live Monitoring Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_REFRESH_TIME` | `10` | Live monitoring refresh interval in seconds |

### File Upload Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_MAX_FILE_SIZE` | `10737418240` | Max upload file size in bytes (10GB) |

### UI Customization

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_MAX_PARTITIONS_DISPLAY` | `10` | Maximum partitions to display in UI |
| `MI_PLOT_WIDTH` | `1450` | Plot width in pixels |
| `MI_PLOT_HEIGHT` | `1800` | Plot height in pixels |

### Security Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_SECURE_COOKIES` | `true` | Enable secure cookies (requires HTTPS) |
| `MI_SSL_ENABLED` | `false` | Enable HTTPS/SSL in Flask application |
| `MI_SSL_CERT` | `/etc/letsencrypt/live/your-domain/fullchain.pem` | Path to SSL certificate file |
| `MI_SSL_KEY` | `/etc/letsencrypt/live/your-domain/privkey.pem` | Path to SSL private key file |

> **Note**: For detailed HTTPS setup instructions, see [HTTPS_SETUP.md](HTTPS_SETUP.md)

---

## 🚀 Usage Examples

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

# Customize plot dimensions
export MI_PLOT_WIDTH=1920
export MI_PLOT_HEIGHT=2400
export MI_MAX_PARTITIONS_DISPLAY=20

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
