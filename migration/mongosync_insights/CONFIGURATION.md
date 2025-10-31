# Configuration Management Guide

This document explains the enhanced configuration management system for Mongosync Insights that supports environment variables and configurable paths.

### **Environment Variables Supported**

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `MI_LOG_FILE` | `insights.log` | Path to log file |
| `MI_HOST` | `127.0.0.1` | Server host address |
| `MI_PORT` | `3030` | Server port number |
| `MI_CONNECTION_STRING` | _(empty)_ | MongoDB connection string |
| `MI_REFRESH_TIME` | `10` | Live monitoring refresh interval in seconds |
| `MI_MAX_FILE_SIZE` | `10737418240` | Max upload file size (10GB) |
| `MI_INTERNAL_DB_NAME` | `mongosync_reserved_for_internal_use` | MongoDB internal database name |
| `MI_MAX_PARTITIONS_DISPLAY` | `10` | Maximum partitions to display in UI |
| `MI_PLOT_WIDTH` | `1450` | Plot width in pixels |
| `MI_PLOT_HEIGHT` | `1800` | Plot height in pixels |
| `MI_POOL_SIZE` | `10` | MongoDB connection pool size |
| `MI_TIMEOUT_MS` | `5000` | MongoDB connection timeout in milliseconds |
| `MI_SECURE_COOKIES` | `true` | Enable secure cookies (requires HTTPS) |
| `MI_SSL_ENABLED` | `false` | Enable HTTPS/SSL in Flask application |
| `MI_SSL_CERT` | `/etc/letsencrypt/live/your-domain/fullchain.pem` | Path to SSL certificate file |
| `MI_SSL_KEY` | `/etc/letsencrypt/live/your-domain/privkey.pem` | Path to SSL private key file |

### **Configuration Priority**

1. **Environment Variables** (highest priority)
2. **Default Values** (lowest priority)

> **Note**: Configuration is entirely environment-variable based. No config files are used.

## 🚀 **Usage Examples**

### **Method 1: Environment Variables**
```bash
# Set custom configuration
export MI_CONFIG="/etc/mongosync/config.ini"
export MI_PORT=8080
export MI_HOST="localhost"
export LOG_LEVEL="DEBUG"
export MI_CONNECTION_STRING="mongodb://user:pass@cluster.mongodb.net/"

# Run the application
python mongosync_insights.py
```

### **Method 2: Mixed Approach**
```bash
# Use custom config file but override specific settings
export MI_CONFIG="/path/to/custom.ini"
export MI_PORT=9090
python mongosync_insights.py
```
