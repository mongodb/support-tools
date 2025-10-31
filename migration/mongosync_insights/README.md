# Mongosync Insights

This tool parses **mongosync** logs and reads the mongosync internal database (metadata), generating interactive plots to assist with monitoring and troubleshooting ongoing MongoDB migrations using mongosync.

## What Does This Tool Do?

Mongosync Insights provides two main capabilities:

1. **Log File Analysis**: Upload and parse mongosync log files to visualize migration progress, data transfer rates, and performance metrics
2. **Live Monitoring**: Connect directly to the mongosync internal database for real-time monitoring of ongoing migrations with auto-refreshing dashboards

## Prerequisites

- **Python**: Version 3.10 or higher
- **pip**: Python package installer
- **MongoDB Access** (for live monitoring): Connection string to the destination cluster where mongosync stores its metadata

## Installation

### 1. Download the Tool

Download or clone the Mongosync Insights folder from this repository.

### 2. Install Dependencies

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
Starting Mongosync Insights v0.7.0.15
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
4. The application will process the log and display plots showing:
   - Total and Copied bytes
   - CEA (Change Event Application) Reads and Writes
   - Collection Copy Reads and Writes
   - Events applied
   - Lag Time

![Mongosync logs analyzer](images/mongosync_log_analyzer.png)

### Option 2: Live Monitoring

1. Enter the MongoDB **connection string** to your destination cluster
   - Format: `mongodb+srv://user:password@cluster.mongodb.net/`
   - This is where mongosync stores its internal metadata
2. Click **"Live Monitor"**
3. The page will refresh automatically every 10 seconds (configurable) showing:
   - Partitions Completed
   - Data Copied
   - Migration Phases
   - Collection Progress

![Mongosync metadata plots](images/mongosync_metadata.png)

## Advanced Configuration

### Environment Variables

Configure the application using environment variables. See **[CONFIGURATION.md](CONFIGURATION.md)** for the complete reference, including:

- Server host and port settings
- MongoDB connection strings
- Refresh intervals
- Upload size limits
- UI customization

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

- **[CONFIGURATION.md](CONFIGURATION.md)** - Complete environment variables reference and configuration options
- **[HTTPS_SETUP.md](HTTPS_SETUP.md)** - Enable HTTPS/SSL for secure deployments
- **[CONNECTION_MANAGEMENT.md](CONNECTION_MANAGEMENT.md)** - MongoDB connection pooling and management

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
