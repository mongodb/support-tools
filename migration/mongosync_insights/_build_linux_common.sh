# Shared Linux packaging logic (sourced by build_amazonlinux.sh, build_rhel.sh, build_ubuntu.sh).
# Not intended to be executed directly.
#
# Caller must set:
#   LINUX_DISTRO   — amazonlinux | rhel | ubuntu
#   PACKAGE_FORMAT — rpm | deb  (default: rpm for amazonlinux/rhel, deb for ubuntu)

: "${LINUX_DISTRO:?LINUX_DISTRO must be set}"
: "${PACKAGE_FORMAT:=rpm}"

linux_common_init() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
    cd "$SCRIPT_DIR"
}

linux_read_version() {
    APP_VERSION=$(python3 -c "
import re, pathlib
m = re.search(
    r'APP_VERSION\s*=\s*\"([^\"]+)\"',
    pathlib.Path('lib/app_config.py').read_text(),
)
print(m.group(1))
")
}

linux_verify_os() {
    if [[ ! -f /etc/os-release ]]; then
        echo "WARNING: /etc/os-release not found; skipping distribution check." >&2
        return 0
    fi
    # shellcheck disable=SC1091
    source /etc/os-release
    local id="${ID:-}"
    local id_like="${ID_LIKE:-}"

    case "$LINUX_DISTRO" in
        amazonlinux)
            if [[ "$id" != "amzn" ]]; then
                echo "WARNING: expected Amazon Linux (ID=amzn), found ID=${id}." >&2
                echo "         Build on Amazon Linux for best compatibility." >&2
            fi
            ;;
        rhel)
            case "$id" in
                rhel | centos | rocky | alma | ol | scientific) ;;
                *)
                    if [[ "$id_like" != *"rhel"* && "$id_like" != *"fedora"* && "$id" != "amzn" ]]; then
                        echo "WARNING: expected RHEL/CentOS family, found ID=${id}." >&2
                        echo "         Build on RHEL, CentOS, Rocky, or AlmaLinux when possible." >&2
                    fi
                    ;;
            esac
            ;;
        ubuntu)
            if [[ "$id" != "ubuntu" && "$id" != "debian" ]]; then
                echo "WARNING: expected Ubuntu/Debian, found ID=${id}." >&2
                echo "         Build on Ubuntu for best compatibility." >&2
            fi
            ;;
    esac
}

linux_print_prereq_help() {
    case "$LINUX_DISTRO:$PACKAGE_FORMAT" in
        amazonlinux:rpm | rhel:rpm)
            cat >&2 <<'EOF'
Install build prerequisites (example):

  # Amazon Linux 2023 / RHEL 8+
  sudo dnf install -y python3.11 python3.11-pip ruby rubygems rpm-build gcc
  sudo gem install fpm

  # Amazon Linux 2 (if python3.11 is unavailable, use a newer python3 or build from source)
  sudo yum install -y python3 ruby rubygems rpm-build gcc
  sudo gem install fpm
EOF
            ;;
        ubuntu:deb)
            cat >&2 <<'EOF'
Install build prerequisites (example):

  sudo apt-get update
  sudo apt-get install -y python3.11 python3.11-venv ruby-rubygems build-essential
  sudo gem install fpm
EOF
            ;;
    esac
}

linux_check_prereqs() {
    local missing=()
    for cmd in python3 pip3 fpm; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    if [[ "$PACKAGE_FORMAT" == "rpm" ]]; then
        if ! command -v rpmbuild &>/dev/null; then
            missing+=("rpmbuild")
        fi
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "ERROR: missing required tools: ${missing[*]}" >&2
        if [[ " ${missing[*]} " == *" fpm "* ]]; then
            echo "       Install fpm with:  sudo gem install fpm" >&2
        fi
        linux_print_prereq_help
        return 1
    fi

    local pyver
    pyver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        echo "ERROR: Python 3.11+ is required (found ${pyver})." >&2
        linux_print_prereq_help
        return 1
    fi
    echo "==> Python ${pyver} detected — OK"
}

linux_pyinstaller_bundle() {
    VENV_DIR="$SCRIPT_DIR/.build_venv_${LINUX_DISTRO}"
    echo "==> Creating virtual environment at ${VENV_DIR}"
    rm -rf "$VENV_DIR"
    python3 -m venv "$VENV_DIR"
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt
    pip install pyinstaller

    echo "==> Running PyInstaller"
    pyinstaller --clean --noconfirm mongosync_insights.spec

    DIST_DIR="$SCRIPT_DIR/dist/mongosync-insights"
    if [[ ! -d "$DIST_DIR" ]]; then
        echo "ERROR: PyInstaller output not found at ${DIST_DIR}" >&2
        return 1
    fi
    echo "==> PyInstaller bundle created at ${DIST_DIR}"
}

linux_prepare_staging() {
    STAGING="$SCRIPT_DIR/dist/pkg-staging-${LINUX_DISTRO}"
    rm -rf "$STAGING"

    INSTALL_PREFIX="/opt/mongosync-insights"

    mkdir -p "$STAGING/$INSTALL_PREFIX"
    cp -a "$DIST_DIR"/. "$STAGING/$INSTALL_PREFIX/"

    mkdir -p "$STAGING/usr/local/bin"
    cat > "$STAGING/usr/local/bin/mongosync-insights" <<'WRAPPER'
#!/usr/bin/env bash
exec /opt/mongosync-insights/mongosync-insights "$@"
WRAPPER
    chmod 755 "$STAGING/usr/local/bin/mongosync-insights"

    mkdir -p "$STAGING/usr/lib/systemd/system"
    cp "$SCRIPT_DIR/mongosync-insights.service" "$STAGING/usr/lib/systemd/system/"

    mkdir -p "$STAGING/etc/mongosync-insights"
    cat > "$STAGING/etc/mongosync-insights/env" <<'ENVFILE'
# Mongosync Insights configuration
# Uncomment and edit the variables you need.
# See CONFIGURATION.md for the full reference.

# MI_HOST=0.0.0.0
# MI_PORT=3030
# MI_CONNECTION_STRING=mongodb+srv://user:pass@cluster.mongodb.net/
# MI_PROGRESS_ENDPOINT_URL=localhost:27182
# MI_REFRESH_TIME=10
# MI_INDEX_BUILD_REFRESH_TIME=60
# MI_SSL_ENABLED=false
# MI_SSL_CERT=/etc/mongosync-insights/cert.pem
# MI_SSL_KEY=/etc/mongosync-insights/key.pem
# LOG_LEVEL=INFO
ENVFILE
    chmod 600 "$STAGING/etc/mongosync-insights/env"

    find "$STAGING" -path '*/.build-id' -type d -exec rm -rf {} + 2>/dev/null || true
}

linux_write_maintainer_scripts() {
    POST_INSTALL=$(mktemp)
    cat > "$POST_INSTALL" <<'SCRIPT'
#!/bin/bash
systemctl daemon-reload 2>/dev/null || true
echo ""
echo "Mongosync Insights installed to /opt/mongosync-insights/"
echo ""
echo "  Configure:  /etc/mongosync-insights/env"
echo "  Start:      sudo systemctl start mongosync-insights"
echo "  Status:     sudo systemctl status mongosync-insights"
echo "  Logs:       journalctl -u mongosync-insights -f"
echo ""
SCRIPT

    PRE_UNINSTALL=$(mktemp)
    cat > "$PRE_UNINSTALL" <<'SCRIPT'
#!/bin/bash
systemctl stop mongosync-insights 2>/dev/null || true
systemctl disable mongosync-insights 2>/dev/null || true
SCRIPT

    POST_UNINSTALL=$(mktemp)
    cat > "$POST_UNINSTALL" <<'SCRIPT'
#!/bin/bash
systemctl daemon-reload 2>/dev/null || true
SCRIPT
}

linux_fpm_iteration() {
    case "$LINUX_DISTRO" in
        amazonlinux) echo "1.amzn" ;;
        rhel) echo "1.el" ;;
        ubuntu) echo "1.ubuntu" ;;
        *) echo "1" ;;
    esac
}

linux_build_package() {
    local iteration pkg_output fpm_target
    iteration=$(linux_fpm_iteration)
    pkg_output="$SCRIPT_DIR/dist"

    linux_write_maintainer_scripts

    echo "==> Building ${PACKAGE_FORMAT} package with fpm (target: ${LINUX_DISTRO})"

    if [[ "$PACKAGE_FORMAT" == "rpm" ]]; then
        fpm_target=rpm
        fpm \
            -s dir \
            -t "$fpm_target" \
            -n mongosync-insights \
            -v "$APP_VERSION" \
            --iteration "$iteration" \
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
            --package "$pkg_output" \
            -C "$STAGING" \
            .
    else
        fpm \
            -s dir \
            -t deb \
            -n mongosync-insights \
            -v "$APP_VERSION" \
            --iteration "$iteration" \
            --license "Apache-2.0" \
            --vendor "MongoDB Support" \
            --description "Mongosync Insights — MongoDB migration monitoring dashboard" \
            --url "https://github.com/mongodb/support-tools" \
            --architecture native \
            --exclude '**/.build-id' \
            --after-install "$POST_INSTALL" \
            --before-remove "$PRE_UNINSTALL" \
            --after-remove "$POST_UNINSTALL" \
            --config-files /etc/mongosync-insights/env \
            --package "$pkg_output" \
            -C "$STAGING" \
            .
    fi

    rm -f "$POST_INSTALL" "$PRE_UNINSTALL" "$POST_UNINSTALL"
}

linux_cleanup() {
    deactivate 2>/dev/null || true
    rm -rf "$VENV_DIR" "$STAGING"
}

linux_print_success() {
    local pattern install_cmd
    if [[ "$PACKAGE_FORMAT" == "rpm" ]]; then
        pattern="$SCRIPT_DIR/dist/mongosync-insights-*.rpm"
        install_cmd="sudo rpm -i"
    else
        pattern="$SCRIPT_DIR/dist/mongosync-insights-*.deb"
        install_cmd="sudo apt install ./"
    fi

    local pkg_file
    pkg_file=$(ls -1 $pattern 2>/dev/null | head -1)
    if [[ -z "$pkg_file" ]]; then
        echo "ERROR: package file not found in dist/" >&2
        return 1
    fi

    echo ""
    echo "==> Package built successfully:"
    echo "    ${pkg_file}"
    echo ""
    echo "    Install on target:"
    if [[ "$PACKAGE_FORMAT" == "rpm" ]]; then
        echo "      ${install_cmd} $(basename "$pkg_file")"
    else
        echo "      ${install_cmd}$(basename "$pkg_file")"
    fi
    echo ""
    echo "    Build on the same or OLDER OS/glibc as your deployment targets."
    echo ""
}

linux_build_main() {
    if [[ "$(uname -s)" != "Linux" ]]; then
        echo "ERROR: Linux package builds must run on Linux (use a VM, container, or CI)." >&2
        exit 1
    fi

    linux_common_init
    linux_verify_os
    linux_read_version

    echo "==> Building Mongosync Insights v${APP_VERSION} for ${LINUX_DISTRO} (${PACKAGE_FORMAT})"

    linux_check_prereqs
    linux_pyinstaller_bundle
    linux_prepare_staging
    linux_build_package
    linux_cleanup
    linux_print_success
}
