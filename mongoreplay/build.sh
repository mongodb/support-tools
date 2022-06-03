#!/bin/bash
set -o errexit
tags=""
if [ ! -z "$1" ]
  then
  	tags="$@"
fi

# make sure we're in the directory where the script lives
SCRIPT_DIR="$(cd "$(dirname ${BASH_SOURCE[0]})" && pwd)"
cd $SCRIPT_DIR

. ./set_goenv.sh
set_goenv || exit

BINARY_EXT=""
UNAME_S=$(PATH="/usr/bin:/bin" uname -s)
    case ${UNAME_S} in
        CYGWIN*)
            BINARY_EXT=".exe"
        ;;
    esac

# remove stale packages
rm -rf vendor/pkg

# download package to local vendor folder
go mod vendor

mkdir -p bin

ec=0
echo "Building mongoreplay..."
export GO111MODULE=on
export GOSUMDB=off
go build -o "bin/mongoreplay$BINARY_EXT" $(buildflags) -ldflags "$(print_ldflags)" -tags "$(print_tags $tags)" "main/mongoreplay.go" || { echo "Error building mongoreplay"; ec=1; }
./bin/mongoreplay${BINARY_EXT} --version | head -1

if [ -t /dev/stdin ]; then
    stty sane
fi

exit $ec
