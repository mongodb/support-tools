# Packaging Mongosync Insights as an RPM

This guide explains how to build a **self-contained RPM** that can be installed on air-gapped (no internet) RHEL/CentOS machines. The RPM includes an embedded Python runtime and all dependencies — the target machine needs **nothing** pre-installed.

## Build Prerequisites

The **build machine** (not the target) needs:

| Requirement | Install |
|---|---|
| Python 3.11+ | `yum install python3.11` or build from source |
| pip | Included with Python 3.11+ |
| Ruby + gem | `yum install ruby rubygems` |
| fpm | `gem install fpm` |
| rpmbuild | `yum install rpm-build` |

> **Important:** Build on the **same or older** RHEL version as the target machine. PyInstaller binaries are glibc-version-specific — a binary built on RHEL 9 will not run on RHEL 8. When in doubt, build on the oldest target you need to support.

## Building the RPM

```bash
cd migration/mongosync_insights
./build_rpm.sh
```

The script will:

1. Read the app version from `app_config.py`
2. Create a temporary Python virtual environment
3. Install all dependencies from `requirements.txt`
4. Run PyInstaller to produce a standalone directory bundle
5. Package everything into an RPM using `fpm`
6. Clean up the temporary venv and staging area

Output:

```
dist/mongosync-insights-<version>-1.x86_64.rpm
```

## Installing on Target RHEL

Copy the RPM to the target machine (USB, SCP, etc.) and install:

```bash
sudo rpm -i mongosync-insights-0.8.0.18-1.x86_64.rpm
```

No internet access is required. No additional packages need to be installed.

**Installed files:**

| Path | Description |
|---|---|
| `/opt/mongosync-insights/` | Application directory (binary + bundled Python + deps) |
| `/usr/local/bin/mongosync-insights` | Wrapper script (adds the tool to `$PATH`) |
| `/usr/lib/systemd/system/mongosync-insights.service` | Systemd unit file |
| `/etc/mongosync-insights/env` | Configuration environment file |

## Configuration

Edit `/etc/mongosync-insights/env` to configure the application:

```bash
# Listen on all interfaces (default: 127.0.0.1)
MI_HOST=0.0.0.0

# Change port (default: 3030)
MI_PORT=8080

# Pre-configure MongoDB connection string for live monitoring
MI_CONNECTION_STRING=mongodb+srv://user:pass@cluster.mongodb.net/

# Pre-configure mongosync progress endpoint
MI_PROGRESS_ENDPOINT_URL=host:port/api/v1/progress

# Dashboard auto-refresh interval in seconds (default: 10)
MI_REFRESH_TIME=5

# Enable HTTPS
MI_SSL_ENABLED=true
MI_SSL_CERT=/etc/mongosync-insights/cert.pem
MI_SSL_KEY=/etc/mongosync-insights/key.pem

# Log level (default: INFO)
LOG_LEVEL=DEBUG
```

See [CONFIGURATION.md](CONFIGURATION.md) for the full reference.

## Running

### Start the service

```bash
sudo systemctl start mongosync-insights
```

### Enable on boot

```bash
sudo systemctl enable mongosync-insights
```

### Check status

```bash
sudo systemctl status mongosync-insights
```

### View logs

```bash
journalctl -u mongosync-insights -f
```

### Run manually (without systemd)

```bash
/opt/mongosync-insights/mongosync-insights
```

Or with environment variables:

```bash
MI_HOST=0.0.0.0 MI_PORT=8080 /opt/mongosync-insights/mongosync-insights
```

## Uninstalling

```bash
sudo rpm -e mongosync-insights
```

This stops the service, removes all installed files, and reloads systemd.

## Upgrading

```bash
sudo rpm -U mongosync-insights-<new-version>-1.x86_64.rpm
```

The configuration file at `/etc/mongosync-insights/env` is preserved during upgrades.

## Architecture Notes

- The RPM is **architecture-specific** (`x86_64` or `aarch64`). Build on the same architecture as the target.
- The RPM is **glibc-version-specific**. Build on the same or older RHEL version as the target.
- The bundled `certifi` CA certificates are frozen at build time. Rebuild the RPM to update them.
- No `libmagic` / `file-libs` system library is required — file type detection uses pure-Python magic-byte inspection.

## Troubleshooting

### "GLIBC_x.xx not found" on the target machine

The RPM was built on a newer OS than the target. Rebuild on the same or older RHEL version.

### Service fails to start

Check the journal for details:
```bash
journalctl -u mongosync-insights --no-pager -n 50
```

Common causes:
- Port already in use — change `MI_PORT` in `/etc/mongosync-insights/env`
- SSL certificate not found — verify paths in the env file
