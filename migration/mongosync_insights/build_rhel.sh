#!/usr/bin/env bash
# =============================================================================
# build_rhel.sh — RPM for Red Hat Enterprise Linux, CentOS, Rocky, AlmaLinux
#
# Build on the same or older RHEL major version as your targets
# (e.g. build on RHEL 8 to support RHEL 8; a RHEL 9 build may not run on RHEL 8).
#
# Prerequisites:
#   sudo dnf install -y python3.11 python3.11-pip ruby rubygems rpm-build gcc
#   sudo gem install fpm
#
# Usage:
#   cd migration/mongosync_insights
#   ./build_rhel.sh
#
# Output:
#   dist/mongosync-insights-<version>-1.el.<arch>.rpm
# =============================================================================
set -euo pipefail

LINUX_DISTRO=rhel
PACKAGE_FORMAT=rpm

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_build_linux_common.sh"
linux_build_main
