# Mongosync Insights

Web dashboard for **mongosync** migrations: log analysis, real-time **Migration Monitoring**, and migration-verifier tracking.

## Workflows

| Hub card | Description |
|----------|-------------|
| **Log analyzer** | Upload and parse mongosync logs, search, and review saved analysis snapshots |
| **Migration monitoring** | Real-time migration progress via mongosync progress API and/or destination metadata |

See **[MIGRATION_MONITORING.md](MIGRATION_MONITORING.md)** for how Migration Monitoring works (inputs, data sources, index-building and verifier fallbacks).

See **[LOG_ANALYZER.md](LOG_ANALYZER.md)** for uploading logs, analysis tabs, snapshots, and the Log Viewer.

## Quick start

**Python 3.11+** required.

Run from source:

```bash
cd migration/mongosync_insights
pip install -r requirements.txt   # if running from source
python3 mongosync_insights.py
```

Open `http://127.0.0.1:3030` (default host/port).

For **other installation options** (macOS/Windows standalone executables, Linux RPM/DEB packages), see **[PACKAGING.md](PACKAGING.md)**.

To **configure** host, port, connection strings, refresh intervals, and other settings via environment variables, see **[CONFIGURATION.md](CONFIGURATION.md)**. Example pre-configuration before starting:

```bash
export MI_CONNECTION_STRING="mongodb+srv://user:pass@cluster.mongodb.net/"
export MI_PROGRESS_ENDPOINT_URL="localhost:27182"
python3 mongosync_insights.py
```

## Documentation

- **[CONFIGURATION.md](CONFIGURATION.md)** — environment variables
- **[LOG_ANALYZER.md](LOG_ANALYZER.md)** — Log Analyzer feature guide
- **[MIGRATION_MONITORING.md](MIGRATION_MONITORING.md)** — Migration Monitoring feature guide
- **[PACKAGING.md](PACKAGING.md)** — standalone builds (macOS, Windows, Linux packages)
- **[CONNECTION_STRING.md](CONNECTION_STRING.md)** — connection string guide
- **[HTTPS_SETUP.md](HTTPS_SETUP.md)** — production HTTPS setup
- **[LOG_VERBOSITY.md](LOG_VERBOSITY.md)** — logging levels

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