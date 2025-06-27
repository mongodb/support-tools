#!/bin/bash

set_goenv() {
    # Error out if not in the same directory as this script
    if [ ! -f ./set_goenv.sh ]; then
        echo "Must be run from mongo-tools top-level directory. Aborting."
        return 1
    fi

    # Set OS-level default Go configuration
    UNAME_S=$(PATH="/usr/bin:/bin" uname -s)
    case $UNAME_S in
        CYGWIN*)
            PREF_GOROOT="c:/golang/go1.12"
            PREF_PATH="/cygdrive/c/golang/go1.12/bin:/cygdrive/c/mingw-w64/x86_64-4.9.1-posix-seh-rt_v3-rev1/mingw64/bin:$PATH"
        ;;
        *)
            PREF_GOROOT="/opt/golang/go1.12"
            # XXX might not need mongodbtoolchain anymore
            PREF_PATH="$PREF_GOROOT/bin:/opt/mongodbtoolchain/v3/bin/:$PATH"
        ;;
    esac

    # Set OS-level compilation flags
    case $UNAME_S in
        CYGWIN*)
            export CGO_CFLAGS="-D_WIN32_WINNT=0x0601 -DNTDDI_VERSION=0x06010000"
            export GOCACHE="C:/windows/temp"
            ;;
        Darwin)
            export CGO_CFLAGS="-mmacosx-version-min=10.11"
            export CGO_LDFLAGS="-mmacosx-version-min=10.11"
            ;;
    esac

    # If GOROOT is not set by the user, configure our preferred Go version and
    # associated path if available or error.
    if [ -z "$GOROOT" ]; then
        if [ -d "$PREF_GOROOT" ]; then
            export GOROOT="$PREF_GOROOT";
            export PATH="$PREF_PATH";
        else
            echo "GOROOT not set and preferred GOROOT '$PREF_GOROOT' doesn't exist. Aborting."
            return 1
        fi
    fi

    return
}

print_ldflags() {
    VersionStr="$(git describe --always)"
    GitCommit="$(git rev-parse HEAD)"
    importpath="main"
    echo "-X ${importpath}.VersionStr=${VersionStr} -X ${importpath}.GitCommit=${GitCommit}"
}

print_tags() {
    tags=""
    if [ ! -z "$1" ]
    then
            tags="$@"
    fi
    UNAME_S=$(PATH="/usr/bin:/bin" uname -s)
    case $UNAME_S in
        Darwin)
            if expr "$tags" : '.*ssl' > /dev/null ; then
                tags="$tags openssl_pre_1.0"
            fi
        ;;
    esac
    echo "$tags"
}

# On linux, we want to set buildmode=pie for ASLR support
buildflags() {
    flags=""
    UNAME_S=$(PATH="/usr/bin:/bin" uname -s)
    case $UNAME_S in
        Linux)
            flags="-buildmode=pie"
        ;;
    esac
    echo "$flags"
}
