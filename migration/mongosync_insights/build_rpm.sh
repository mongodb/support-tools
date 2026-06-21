#!/usr/bin/env bash
# =============================================================================
# build_rpm.sh — backward-compatible alias for build_rhel.sh
#
# Prefer ./build_rhel.sh, ./build_amazonlinux.sh, or ./build_ubuntu.sh so the
# package metadata matches your target distribution.
# =============================================================================
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/build_rhel.sh" "$@"
