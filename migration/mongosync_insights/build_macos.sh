#!/usr/bin/env bash
# =============================================================================
# build_macos.sh — Build single-file Mongosync Insights executables for macOS
#
# Produces one self-contained binary per architecture (no Python install needed
# on the target Mac). PyInstaller bundles the interpreter and dependencies.
#
# Prerequisites (build machine: macOS only):
#   - Python 3.11+ for each architecture you want to build
#   - On Apple Silicon, an x86_64 (Rosetta) Python is required for Intel builds
#     (e.g. install python.org universal2 or `arch -x86_64 brew install python@3.12`)
#
# Usage:
#   cd migration/mongosync_insights
#   chmod +x build_macos.sh
#   ./build_macos.sh              # native CPU only
#   ./build_macos.sh --arch all   # arm64 + x86_64 when both Pythons are available
#   ./build_macos.sh --arch arm64
#   ./build_macos.sh --arch x86_64
#
# Output (examples):
#   dist/mongosync-insights-0.8.2.8-macos-arm64
#   dist/mongosync-insights-0.8.2.8-macos-x86_64
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ARCH_CHOICE="native"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --arch)
            ARCH_CHOICE="${2:?--arch requires a value: native, arm64, x86_64, or all}"
            shift 2
            ;;
        -h | --help)
            sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1 (try --help)" >&2
            exit 1
            ;;
    esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "ERROR: build_macos.sh must be run on macOS." >&2
    exit 1
fi

APP_VERSION=$(
    python3 -c "
import re, pathlib
m = re.search(
    r'APP_VERSION\s*=\s*\"([^\"]+)\"',
    pathlib.Path('lib/app_config.py').read_text(),
)
print(m.group(1))
"
)
echo "==> Building Mongosync Insights v${APP_VERSION} for macOS"

# ---------------------------------------------------------------------------
# Architecture helpers
# ---------------------------------------------------------------------------
host_machine() {
    uname -m
}

python_machine() {
    local py_cmd=("$@")
    "${py_cmd[@]}" -c "import platform; print(platform.machine())"
}

# Returns 0 if the interpreter's platform.machine() matches TARGET_ARCH.
python_matches_arch() {
    local target_arch=$1
    shift
    local py_cmd=("$@")
    local actual
    actual=$(python_machine "${py_cmd[@]}")
    case "$target_arch" in
        arm64) [[ "$actual" == "arm64" ]] ;;
        x86_64) [[ "$actual" == "x86_64" ]] ;;
        *) return 1 ;;
    esac
}

# Resolve a shell command prefix array for a target architecture.
resolve_python_cmd() {
    local target_arch=$1
    local host
    host=$(host_machine)

    case "$target_arch" in
        arm64)
            if [[ "$host" != "arm64" ]]; then
                echo "ERROR: arm64 builds require an Apple Silicon Mac." >&2
                return 1
            fi
            if python_matches_arch arm64 python3; then
                echo "python3"
                return 0
            fi
            ;;
        x86_64)
            if [[ "$host" == "x86_64" ]]; then
                if python_matches_arch x86_64 python3; then
                    echo "python3"
                    return 0
                fi
            elif [[ "$host" == "arm64" ]]; then
                if python_matches_arch x86_64 arch -x86_64 python3; then
                    echo "arch -x86_64 python3"
                    return 0
                fi
                echo "ERROR: x86_64 Python not found." >&2
                echo "       Install a Rosetta (x86_64) Python, for example:" >&2
                echo "         arch -x86_64 /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"" >&2
                echo "         arch -x86_64 brew install python@3.12" >&2
                return 1
            fi
            ;;
    esac
    echo "ERROR: no Python 3.11+ found for architecture ${target_arch}." >&2
    return 1
}

archs_to_build() {
    local host choice
    host=$(host_machine)
    choice="$ARCH_CHOICE"

    case "$choice" in
        native)
            if [[ "$host" == "arm64" ]]; then
                echo "arm64"
            else
                echo "x86_64"
            fi
            ;;
        arm64 | x86_64)
            echo "$choice"
            ;;
        all)
            echo "arm64"
            echo "x86_64"
            ;;
        *)
            echo "ERROR: invalid --arch value: ${choice}" >&2
            return 1
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Build one architecture
# ---------------------------------------------------------------------------
build_one() {
    local target_arch=$1
    local py_line
    py_line=$(resolve_python_cmd "$target_arch") || return 1

    # shellcheck disable=SC2206
    local py_cmd=($py_line)

    if ! "${py_cmd[@]}" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        local ver
        ver=$("${py_cmd[@]}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "?")
        echo "ERROR: Python 3.11+ required for ${target_arch} (found ${ver})." >&2
        return 1
    fi

    local actual_arch venv_dir dist_name output_path
    actual_arch=$(python_machine "${py_cmd[@]}")
    echo ""
    echo "==> Building for ${target_arch} (Python ${actual_arch})"

    venv_dir="${SCRIPT_DIR}/.build_venv_macos_${target_arch}"
    rm -rf "$venv_dir"
    "${py_cmd[@]}" -m venv "$venv_dir"
    # shellcheck disable=SC1091
    source "${venv_dir}/bin/activate"

    pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt
    pip install pyinstaller

    rm -rf build dist/mongosync-insights
    pyinstaller --clean --noconfirm mongosync_insights_onefile.spec

    deactivate 2>/dev/null || true
    rm -rf "$venv_dir"

    if [[ ! -f "${SCRIPT_DIR}/dist/mongosync-insights" ]]; then
        echo "ERROR: PyInstaller did not produce dist/mongosync-insights" >&2
        return 1
    fi

    dist_name="mongosync-insights-${APP_VERSION}-macos-${target_arch}"
    output_path="${SCRIPT_DIR}/dist/${dist_name}"
    mv "${SCRIPT_DIR}/dist/mongosync-insights" "$output_path"
    chmod 755 "$output_path"

    # Clear quarantine bit if present (e.g. after copying from another machine)
    xattr -cr "$output_path" 2>/dev/null || true

    echo "==> Built: ${output_path}"
    file "$output_path"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
built=0
failed=0
skipped=0

while IFS= read -r target_arch; do
    if build_one "$target_arch"; then
        built=$((built + 1))
    else
        if [[ "$ARCH_CHOICE" == "all" ]]; then
            echo "==> Skipping ${target_arch} (see errors above)" >&2
            skipped=$((skipped + 1))
        else
            failed=1
        fi
    fi
done < <(archs_to_build)

echo ""
if [[ $built -eq 0 ]]; then
    echo "ERROR: no binaries were built." >&2
    exit 1
fi

echo "==> Done. ${built} binary/binaries in ${SCRIPT_DIR}/dist/"
if [[ $skipped -gt 0 ]]; then
    echo "    (${skipped} architecture(s) skipped — install the matching Python to build them)"
fi

if [[ $failed -ne 0 ]]; then
    exit 1
fi

echo ""
echo "Run (pick the binary that matches your Mac's CPU):"
echo "  ./dist/mongosync-insights-${APP_VERSION}-macos-arm64      # Apple Silicon"
echo "  ./dist/mongosync-insights-${APP_VERSION}-macos-x86_64   # Intel"
echo ""
echo "  MI_HOST=127.0.0.1 MI_PORT=3030 ./dist/mongosync-insights-..."
