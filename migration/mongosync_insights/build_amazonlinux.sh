#!/usr/bin/env bash
# =============================================================================
# build_amazonlinux.sh — RPM for Amazon Linux (AL2, AL2023)
#
# Build on Amazon Linux matching (or older than) your deployment target.
# PyInstaller binaries are glibc-specific.
#
# Prerequisites:
#   sudo dnf install -y python3.11 python3.11-pip ruby rubygems rpm-build gcc
#   sudo gem install fpm
#
# Usage:
#   cd migration/mongosync_insights
#   ./build_amazonlinux.sh
#
# Output:
#   dist/mongosync-insights-<version>-1.amzn.<arch>.rpm
# =============================================================================
set -euo pipefail

LINUX_DISTRO=amazonlinux
PACKAGE_FORMAT=rpm

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_build_linux_common.sh"
linux_build_main
