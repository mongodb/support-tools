#!/usr/bin/env bash
# =============================================================================
# build_rpm.sh — Build a self-contained RPM for Mongosync Insights
#
# The RPM bundles the Python interpreter, all dependencies, templates, images,
# and JSON configs via PyInstaller so the target machine needs nothing extra.
#
# Prerequisites (build machine only):
#   - Python 3.11+
#   - pip
#   - ruby + gem  (for fpm)
#   - fpm:  gem install fpm
#   - rpmbuild:  yum install rpm-build  (fpm uses it under the hood)
#
# Usage:
#   cd migration/mongosync_insights
#   chmod +x build_rpm.sh
#   ./build_rpm.sh
#
# Output:
#   ./dist/mongosync-insights-<version>-1.x86_64.rpm
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---------------------------------------------------------------------------
# 1. Read version from app_config.py
# ---------------------------------------------------------------------------
APP_VERSION=$(python3 -c "
import re, pathlib
m = re.search(r'APP_VERSION\s*=\s*\"([^\"]+)\"', pathlib.Path('app_config.py').read_text())
print(m.group(1))
")
echo "==> Building Mongosync Insights v${APP_VERSION}"

# ---------------------------------------------------------------------------
# 2. Check build prerequisites
# ---------------------------------------------------------------------------
for cmd in python3 pip3 fpm rpmbuild; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: '$cmd' is required but not found in PATH." >&2
        if [[ "$cmd" == "fpm" ]]; then
            echo "       Install it with:  gem install fpm" >&2
        fi
        exit 1
    fi
done

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
    echo "==> Python ${PYTHON_VERSION} detected — OK"
else
    echo "ERROR: Python 3.11+ is required (found ${PYTHON_VERSION})." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. Create a clean virtual environment
# ---------------------------------------------------------------------------
VENV_DIR="$SCRIPT_DIR/.build_venv"
echo "==> Creating virtual environment at ${VENV_DIR}"
rm -rf "$VENV_DIR"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install pyinstaller

# ---------------------------------------------------------------------------
# 4. Run PyInstaller
# ---------------------------------------------------------------------------
echo "==> Running PyInstaller"
pyinstaller --clean --noconfirm mongosync_insights.spec

DIST_DIR="$SCRIPT_DIR/dist/mongosync-insights"
if [[ ! -d "$DIST_DIR" ]]; then
    echo "ERROR: PyInstaller output directory not found at ${DIST_DIR}" >&2
    exit 1
fi
echo "==> PyInstaller bundle created at ${DIST_DIR}"

# ---------------------------------------------------------------------------
# 5. Prepare RPM staging area
# ---------------------------------------------------------------------------
STAGING="$SCRIPT_DIR/dist/rpm-staging"
rm -rf "$STAGING"

INSTALL_PREFIX="/opt/mongosync-insights"

# Application files
mkdir -p "$STAGING/$INSTALL_PREFIX"
cp -a "$DIST_DIR"/. "$STAGING/$INSTALL_PREFIX/"

# Wrapper script
mkdir -p "$STAGING/usr/local/bin"
cat > "$STAGING/usr/local/bin/mongosync-insights" <<'WRAPPER'
#!/usr/bin/env bash
exec /opt/mongosync-insights/mongosync-insights "$@"
WRAPPER
chmod 755 "$STAGING/usr/local/bin/mongosync-insights"

# Systemd service file
mkdir -p "$STAGING/usr/lib/systemd/system"
cp "$SCRIPT_DIR/mongosync-insights.service" "$STAGING/usr/lib/systemd/system/"

# Default environment file
mkdir -p "$STAGING/etc/mongosync-insights"
cat > "$STAGING/etc/mongosync-insights/env" <<'ENVFILE'
# Mongosync Insights configuration
# Uncomment and edit the variables you need.
# See CONFIGURATION.md for the full reference.

# MI_HOST=0.0.0.0
# MI_PORT=3030
# MI_CONNECTION_STRING=mongodb+srv://user:pass@cluster.mongodb.net/
# MI_PROGRESS_ENDPOINT_URL=host:port/api/v1/progress
# MI_REFRESH_TIME=10
# MI_SSL_ENABLED=false
# MI_SSL_CERT=/etc/mongosync-insights/cert.pem
# MI_SSL_KEY=/etc/mongosync-insights/key.pem
# LOG_LEVEL=INFO
ENVFILE

# ---------------------------------------------------------------------------
# 6. Build the RPM with fpm
# ---------------------------------------------------------------------------
echo "==> Building RPM with fpm"

# Post-install script: reload systemd
POST_INSTALL=$(mktemp)
cat > "$POST_INSTALL" <<'SCRIPT'
#!/bin/bash
systemctl daemon-reload 2>/dev/null || true
echo ""
echo "Mongosync Insights installed to /opt/mongosync-insights/"
echo ""
echo "  Configure:  /etc/mongosync-insights/env"
echo "  Start:      systemctl start mongosync-insights"
echo "  Status:     systemctl status mongosync-insights"
echo "  Logs:       journalctl -u mongosync-insights -f"
echo ""
SCRIPT

# Pre-uninstall script: stop the service
PRE_UNINSTALL=$(mktemp)
cat > "$PRE_UNINSTALL" <<'SCRIPT'
#!/bin/bash
systemctl stop mongosync-insights 2>/dev/null || true
systemctl disable mongosync-insights 2>/dev/null || true
SCRIPT

# Post-uninstall script: reload systemd
POST_UNINSTALL=$(mktemp)
cat > "$POST_UNINSTALL" <<'SCRIPT'
#!/bin/bash
systemctl daemon-reload 2>/dev/null || true
SCRIPT

RPM_OUTPUT="$SCRIPT_DIR/dist"

# Remove .build-id symlinks that PyInstaller copies from system libraries.
# These conflict with RHEL system packages (ncurses-libs, zlib, openssl-libs, etc.)
find "$STAGING" -path '*/.build-id' -type d -exec rm -rf {} + 2>/dev/null || true

fpm \
    -s dir \
    -t rpm \
    -n mongosync-insights \
    -v "$APP_VERSION" \
    --iteration 1 \
    --license "Apache-2.0" \
    --vendor "MongoDB Support" \
    --description "Mongosync Insights — MongoDB migration monitoring dashboard" \
    --url "https://github.com/mongodb/support-tools" \
    --architecture native \
    --rpm-auto-add-directories \
    --rpm-rpmbuild-define '_build_id_links none' \
    --exclude '**/.build-id' \
    --after-install "$POST_INSTALL" \
    --before-remove "$PRE_UNINSTALL" \
    --after-remove "$POST_UNINSTALL" \
    --config-files /etc/mongosync-insights/env \
    --package "$RPM_OUTPUT" \
    -C "$STAGING" \
    .

rm -f "$POST_INSTALL" "$PRE_UNINSTALL" "$POST_UNINSTALL"

# ---------------------------------------------------------------------------
# 7. Clean up
# ---------------------------------------------------------------------------
deactivate 2>/dev/null || true
rm -rf "$VENV_DIR" "$STAGING"

RPM_FILE=$(ls -1 "$RPM_OUTPUT"/mongosync-insights-*.rpm 2>/dev/null | head -1)
if [[ -n "$RPM_FILE" ]]; then
    echo ""
    echo "==> RPM built successfully:"
    echo "    ${RPM_FILE}"
    echo ""
    echo "    Install on target:  sudo rpm -i $(basename "$RPM_FILE")"
    echo ""
else
    echo "ERROR: RPM file not found in ${RPM_OUTPUT}" >&2
    exit 1
fi
