# Packaging Mongosync Insights

Self-contained builds bundle Python and dependencies so target machines do not need `pip install`.

## Build scripts overview

| Platform | Script | Build where? | Output |
|---|---|---|---|
| **macOS** | `build_macos.sh` | macOS only | `dist/mongosync-insights-<version>-macos-{arm64,x86_64}` |
| **Windows** | `build_windows.ps1` / `build_windows.bat` | Windows only | `dist\mongosync-insights-<version>-windows-{x86_64,arm64}.exe` |
| **Amazon Linux** | `build_amazonlinux.sh` | Amazon Linux 2 / 2023 | `dist/mongosync-insights-<version>-1.amzn.<arch>.rpm` |
| **RHEL / CentOS** | `build_rhel.sh` | RHEL, CentOS, Rocky, AlmaLinux | `dist/mongosync-insights-<version>-1.el.<arch>.rpm` |
| **Ubuntu** | `build_ubuntu.sh` | Ubuntu 22.04+ | `dist/mongosync-insights_<version>-1.ubuntu_<arch>.deb` |
| **RHEL (alias)** | `build_rpm.sh` | Same as `build_rhel.sh` | Same as RHEL |

Shared implementation: Linux scripts source `_build_linux_common.sh`. macOS/Windows use `mongosync_insights_onefile.spec`; Linux packages use `mongosync_insights.spec` (directory bundle under `/opt/mongosync-insights`).

> **Cross-compile:** PyInstaller targets the OS it runs on. You cannot build Windows `.exe` or macOS binaries from Linux, or Linux packages from macOS. Use a VM, native host, or CI for each platform.

---

## macOS (single-file executable)

Use `build_macos.sh` on a Mac to produce **one runnable file per CPU architecture**.

| Output | Mac type |
|---|---|
| `dist/mongosync-insights-<version>-macos-arm64` | Apple Silicon (M1/M2/M3/…) |
| `dist/mongosync-insights-<version>-macos-x86_64` | Intel |

### Prerequisites

| Requirement | Notes |
|---|---|
| macOS build host | Script refuses to run on Linux/Windows |
| Python 3.11+ (arm64) | System or Homebrew `python3` on Apple Silicon |
| Python 3.11+ (x86_64) | Only for Intel binaries on Apple Silicon — use a **separate** x86_64 Homebrew in `/usr/local` or python.org (not `arch -x86_64 brew` against `/opt/homebrew`) |

### Building

```bash
cd migration/mongosync_insights
./build_macos.sh              # native CPU only
./build_macos.sh --arch arm64
./build_macos.sh --arch x86_64
./build_macos.sh --arch all   # both when both Pythons are installed
```

### Running

```bash
chmod +x dist/mongosync-insights-*-macos-arm64
./dist/mongosync-insights-*-macos-arm64
```

Environment variables: `MI_HOST`, `MI_PORT`, `MI_CONNECTION_STRING`, `MI_PROGRESS_ENDPOINT_URL`, etc. See [CONFIGURATION.md](CONFIGURATION.md) and [MIGRATION_MONITORING.md](MIGRATION_MONITORING.md).

If macOS blocks the binary (“damaged” / unidentified developer):

```bash
xattr -cr dist/mongosync-insights-*-macos-*
```

---

## Windows (single-file `.exe`)

Use `build_windows.ps1` **on a Windows PC**. You cannot produce a Windows `.exe` from macOS or Linux.

| Output | Target PC |
|---|---|
| `dist\mongosync-insights-<version>-windows-x86_64.exe` | Typical 64-bit Windows (Intel/AMD) |
| `dist\mongosync-insights-<version>-windows-arm64.exe` | Windows on ARM |

### Prerequisites

[Python 3.11+ for Windows](https://www.python.org/downloads/windows/) (64-bit), with **Add python.exe to PATH** enabled.

### Building

```powershell
cd migration\mongosync_insights
.\build_windows.ps1
.\build_windows.ps1 -Arch x86_64
.\build_windows.ps1 -Arch arm64
.\build_windows.ps1 -Arch all    # when both Pythons are installed
```

Or from cmd: `build_windows.bat`

### Running

```powershell
.\dist\mongosync-insights-*-windows-x86_64.exe
```

Environment variables: `MI_HOST`, `MI_PORT`, `MI_CONNECTION_STRING`, `MI_PROGRESS_ENDPOINT_URL`, etc. See [CONFIGURATION.md](CONFIGURATION.md) and [MIGRATION_MONITORING.md](MIGRATION_MONITORING.md).

Windows Defender may flag new unsigned executables; sign the binary or allowlist it in your environment if needed.

---

## Linux packages (RPM / DEB)

Packages install under `/opt/mongosync-insights` with systemd and `/etc/mongosync-insights/env`. The target needs **no pip install**.

> **Important:** Build on **Linux**, on the **same or older** OS/glibc as your deployment. A binary built on RHEL 9 or Ubuntu 24.04 may not run on older releases. When in doubt, build on the oldest target you support.

### Prerequisites (all Linux scripts)

| Tool | RPM distros | Ubuntu |
|---|---|---|
| Python 3.11+ | `python3.11`, `python3.11-pip` | `python3.11`, `python3.11-venv` |
| fpm | `sudo gem install fpm` | `sudo gem install fpm` |
| Ruby | `ruby`, `rubygems` | `ruby-rubygems` |
| rpmbuild | `rpm-build` (RPM only) | not required for `.deb` |
| Compiler | `gcc` / `build-essential` | `build-essential` |

### Amazon Linux

```bash
cd migration/mongosync_insights
# AL2023
sudo dnf install -y python3.11 python3.11-pip ruby rubygems rpm-build gcc
# AL2 (adjust python package if 3.11 is unavailable)
sudo yum install -y python3 ruby rubygems rpm-build gcc
sudo gem install fpm
./build_amazonlinux.sh
```

### Red Hat / CentOS (RHEL family)

```bash
cd migration/mongosync_insights
sudo dnf install -y python3.11 python3.11-pip ruby rubygems rpm-build gcc
sudo gem install fpm
./build_rhel.sh
# or: ./build_rpm.sh   (alias)
```

### Ubuntu

```bash
cd migration/mongosync_insights
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv ruby-rubygems build-essential
sudo gem install fpm
./build_ubuntu.sh
```

### What the Linux scripts do

1. Read the app version from `lib/app_config.py`
2. Create a temporary virtual environment and install dependencies
3. Run PyInstaller (`mongosync_insights.spec`)
4. Stage files under `/opt/mongosync-insights`, systemd unit, and config
5. Build RPM or DEB with **fpm**
6. Clean up the venv and staging directory

### Installing on target

**RPM (Amazon Linux, RHEL, CentOS):**

```bash
sudo rpm -i mongosync-insights-<version>-1.el.x86_64.rpm
# or
sudo dnf install ./mongosync-insights-*.rpm
```

**DEB (Ubuntu):**

```bash
sudo apt install ./mongosync-insights_*-1.ubuntu_amd64.deb
```

No internet is required on the target beyond installing the package.

**Installed files:**

| Path | Description |
|---|---|
| `/opt/mongosync-insights/` | Application (binary + bundled Python + deps) |
| `/usr/local/bin/mongosync-insights` | Wrapper on `$PATH` |
| `/usr/lib/systemd/system/mongosync-insights.service` | Systemd unit |
| `/etc/mongosync-insights/env` | Configuration (preserved on upgrade) |

### Configuration (Linux packages)

Edit `/etc/mongosync-insights/env`:

```bash
MI_HOST=0.0.0.0
MI_PORT=8080
MI_CONNECTION_STRING=mongodb+srv://user:pass@cluster.mongodb.net/
MI_PROGRESS_ENDPOINT_URL=localhost:27182
MI_REFRESH_TIME=5
MI_INDEX_BUILD_REFRESH_TIME=60
MI_SSL_ENABLED=true
MI_SSL_CERT=/etc/mongosync-insights/cert.pem
MI_SSL_KEY=/etc/mongosync-insights/key.pem
LOG_LEVEL=DEBUG
```

See [CONFIGURATION.md](CONFIGURATION.md) for the full reference.

### Running (Linux packages)

```bash
sudo systemctl start mongosync-insights
sudo systemctl enable mongosync-insights
sudo systemctl status mongosync-insights
journalctl -u mongosync-insights -f
```

Manual run:

```bash
MI_HOST=0.0.0.0 MI_PORT=8080 /opt/mongosync-insights/mongosync-insights
```

### Uninstalling

**RPM:**

```bash
sudo rpm -e mongosync-insights
```

**DEB:**

```bash
sudo apt remove mongosync-insights
```

### Upgrading

**RPM:**

```bash
sudo rpm -U mongosync-insights-<new-version>-1.el.x86_64.rpm
```

**DEB:**

```bash
sudo apt install ./mongosync-insights_<new-version>-1.ubuntu_amd64.deb
```

---

## Architecture notes

- Packages are **CPU-specific** (`x86_64`, `aarch64`/`arm64`). Build on the same architecture as the target.
- Linux binaries are **glibc-specific**. Build on the same or older distro major version as production.
- macOS/Windows one-file builds extract to a temp directory at runtime; Linux packages use `/opt/mongosync-insights`.
- Bundled `certifi` CA certificates are frozen at build time; rebuild to update them.
- No `libmagic` is required — file type detection uses pure-Python magic-byte inspection.

## Troubleshooting

### "GLIBC_x.xx not found" (Linux)

The package was built on a newer OS than the target. Rebuild on the same or older release.

### Service fails to start (Linux)

```bash
journalctl -u mongosync-insights --no-pager -n 50
```

Common causes: port in use (`MI_PORT`), missing SSL cert paths in `/etc/mongosync-insights/env`.

### macOS "damaged" or won't open

```bash
xattr -cr dist/mongosync-insights-*-macos-*
```

### Windows SmartScreen / Defender

Sign the executable or allowlist in your environment.

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