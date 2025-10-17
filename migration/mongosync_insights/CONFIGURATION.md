# Configuration Management Guide

This document explains the enhanced configuration management system for Mongosync Insights that supports environment variables and configurable paths.

## 🎯 **Problem Solved**

Previously, the application had:
- Hardcoded config file path (`config.ini`)
- No environment variable support
- Basic logging configuration
- No configuration validation

## ✅ **New Configuration System**

### **Environment Variables Supported**

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGOSYNC_CONFIG` | `config.ini` | Path to configuration file |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `MONGOSYNC_LOG_FILE` | `mongosync_insights.log` | Path to log file |
| `MONGOSYNC_HOST` | `0.0.0.0` | Server host address |
| `MONGOSYNC_PORT` | `3030` | Server port number |
| `MONGOSYNC_CONNECTION_STRING` | _(empty)_ | MongoDB connection string |
| `MONGOSYNC_REFRESH_TIME` | `10` | Live monitoring refresh interval in seconds |
| `MONGOSYNC_MAX_FILE_SIZE` | `10737418240` | Max upload file size (10GB) |
| `MONGOSYNC_INTERNAL_DB_NAME` | `mongosync_reserved_for_internal_use` | MongoDB internal database name |
| `MONGOSYNC_MAX_PARTITIONS_DISPLAY` | `10` | Maximum partitions to display in UI |
| `MONGOSYNC_PLOT_WIDTH` | `1450` | Plot width in pixels |
| `MONGOSYNC_PLOT_HEIGHT` | `1800` | Plot height in pixels |
| `MONGOSYNC_APP_NAME` | `Mongosync Insights` | Application name displayed in UI |
| `MONGOSYNC_APP_VERSION` | `0.6.9.2` | Application version displayed in UI |
| `MONGOSYNC_POOL_SIZE` | `10` | MongoDB connection pool size |
| `MONGOSYNC_TIMEOUT_MS` | `5000` | MongoDB connection timeout in milliseconds |

### **Configuration Priority**

1. **Environment Variables** (highest priority)
2. **Configuration File** (config.ini)
3. **Default Values** (lowest priority)

## 🚀 **Usage Examples**

### **Method 1: Environment Variables**
```bash
# Set custom configuration
export MONGOSYNC_CONFIG="/etc/mongosync/config.ini"
export MONGOSYNC_PORT=8080
export MONGOSYNC_HOST="localhost"
export LOG_LEVEL="DEBUG"
export MONGOSYNC_CONNECTION_STRING="mongodb://user:pass@cluster.mongodb.net/"

# Run the application
python mongosync_insights.py
```

### **Method 2: Configuration File**
```ini
[LiveMonitor]
connectionString = mongodb://localhost:27017/
refreshTime = 5
```

### **Method 3: Mixed Approach**
```bash
# Use custom config file but override specific settings
export MONGOSYNC_CONFIG="/path/to/custom.ini"
export MONGOSYNC_PORT=9090
python mongosync_insights.py
```

## 📁 **File Structure**

```
mongosync_insights/
├── app_config.py           # Configuration management module
├── mongosync_insights.py   # Main app (updated to use new config)
├── mongosync_plot_logs.py  # Updated to use centralized logging
├── mongosync_plot_metadata.py # Updated to use centralized config
└── config.ini              # Configuration file (auto-created if missing)
```

## 🔧 **Configuration Functions**

### **`load_config()`**
Loads configuration with environment variable overrides:
```python
from app_config import load_config
config = load_config()
connection_string = config['LiveMonitor']['connectionString']
```

### **`setup_logging()`**
Configures logging based on environment variables:
```python
from app_config import setup_logging
logger = setup_logging()
logger.info("Application started")
```

### **`validate_config()`**
Validates configuration on startup:
```python
from app_config import validate_config
try:
    validate_config()
except (PermissionError, ValueError) as e:
    print(f"Configuration error: {e}")
    exit(1)
```

### **`get_app_info()`**
Gets application information:
```python
from app_config import get_app_info
info = get_app_info()
print(f"Running {info['name']} v{info['version']} on {info['host']}:{info['port']}")
```

## 🔗 **Database Connection Management**

The application now uses advanced connection pooling and caching for improved performance:

### **Connection Pool Settings**
```bash
# Configure connection pool
export MONGOSYNC_POOL_SIZE=20           # Increase pool size for high traffic
export MONGOSYNC_TIMEOUT_MS=10000       # 10 second timeout for slow networks
```

### **Connection Features**
- **Connection Pooling**: Reuses connections across requests
- **LRU Caching**: Caches MongoDB client instances
- **Automatic Retry**: Built-in retry logic for failed connections
- **Connection Validation**: Validates connection strings before use

### **Performance Benefits**
- ⚡ **Faster Response Times**: No connection overhead per request
- 🔄 **Resource Efficiency**: Connection pooling prevents exhaustion
- 🚀 **Improved Throughput**: Cached connections eliminate setup time

For detailed information, see [CONNECTION_MANAGEMENT.md](CONNECTION_MANAGEMENT.md).

## 🐳 **Docker Support**

The new configuration system is Docker-friendly:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

# Set environment variables
ENV MONGOSYNC_HOST=0.0.0.0
ENV MONGOSYNC_PORT=3030
ENV LOG_LEVEL=INFO
ENV MONGOSYNC_LOG_FILE=/var/log/mongosync_insights.log

EXPOSE 3030
CMD ["python", "mongosync_insights.py"]
```

## 🔒 **Security Considerations**

### **File Upload Security**
- **File Size Limits**: Configurable maximum file size (default: 10GB)
- **File Type Validation**: Only `.log`, `.json`, and `.out` files allowed
- **Filename Sanitization**: Uses `secure_filename()` to prevent path traversal
- **Dual Validation**: Both Flask-level and application-level size checking

### **Sensitive Data**
- Use environment variables for sensitive data (connection strings, passwords)
- Avoid storing credentials in configuration files
- Use Docker secrets or Kubernetes secrets in production

### **File Permissions**
- Configuration files should be readable by the application user
- Log directories should be writable by the application user
- The system validates permissions on startup

## 🎯 **Best Practices**

### **Development**
```bash
# Use local config file with custom UI settings
export MONGOSYNC_CONFIG="dev_config.ini"
export LOG_LEVEL="DEBUG"
export MONGOSYNC_REFRESH_TIME="5"
export MONGOSYNC_MAX_PARTITIONS_DISPLAY="5"
export MONGOSYNC_PLOT_WIDTH="1200"
export MONGOSYNC_PLOT_HEIGHT="1600"
python mongosync_insights.py
```

### **Production**
```bash
# Use environment variables for all settings
export MONGOSYNC_CONNECTION_STRING="mongodb+srv://prod-cluster/"
export MONGOSYNC_HOST="0.0.0.0"
export MONGOSYNC_PORT="3030"
export LOG_LEVEL="INFO"
export MONGOSYNC_LOG_FILE="/var/log/mongosync/app.log"
python mongosync_insights.py
```

### **Testing**
```bash
# Use temporary config for testing
export MONGOSYNC_CONFIG="/tmp/test_config.ini"
export MONGOSYNC_PORT="0"  # Use random available port
python -m pytest
```

## 🚨 **Error Handling**

The system validates configuration on startup and provides clear error messages:

```bash
# Invalid port
$ MONGOSYNC_PORT=99999 python mongosync_insights.py
Configuration error: Invalid port number: 99999. Must be between 1 and 65535.

# Unreadable config file
$ MONGOSYNC_CONFIG="/root/config.ini" python mongosync_insights.py
Configuration error: Cannot read configuration file: /root/config.ini

# Unwritable log directory
$ MONGOSYNC_LOG_FILE="/root/app.log" python mongosync_insights.py
Configuration error: Cannot write to log directory: /root
```

## 📊 **Startup Logging**

The application now logs detailed startup information:

```
2024-01-01 12:00:00,000 - INFO - Starting Mongosync Insights v0.6.9
2024-01-01 12:00:00,001 - INFO - Configuration file: config.ini
2024-01-01 12:00:00,002 - INFO - Log file: mongosync_insights.log
2024-01-01 12:00:00,003 - INFO - Server: 0.0.0.0:3030
```

## 🔄 **Migration from Old System**

The new system is **backward compatible**:
- Existing `config.ini` files continue to work
- Default values match the old hardcoded values
- No changes required for basic usage

## 🧪 **Testing Configuration**

```python
# Test configuration loading
from app_config import load_config, get_app_info
config = load_config()
print("Connection:", config['LiveMonitor']['connectionString'])

# Test with environment variables
import os
os.environ['MONGOSYNC_PORT'] = '8080'
info = get_app_info()
print(f"Port: {info['port']}")  # Should print 8080
```

This enhanced configuration system provides flexibility, security, and maintainability while remaining backward compatible with existing deployments.
