#!/usr/bin/env bash
# =============================================================================
# build_ubuntu.sh — .deb for Ubuntu (22.04+ recommended)
#
# Build on the same or older Ubuntu LTS as your deployment target.
#
# Prerequisites:
#   sudo apt-get update
#   sudo apt-get install -y python3.11 python3.11-venv ruby-rubygems build-essential
#   sudo gem install fpm
#
# Usage:
#   cd migration/mongosync_insights
#   ./build_ubuntu.sh
#
# Output:
#   dist/mongosync-insights_<version>-1.ubuntu_<arch>.deb
# =============================================================================
set -euo pipefail

LINUX_DISTRO=ubuntu
PACKAGE_FORMAT=deb

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_build_linux_common.sh"
linux_build_main
