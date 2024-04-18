#!/bin/bash

set -x
set -e
set -o pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

DEFAULT_WORKDIR=$(pwd)/work-dir
export WORKDIR=${WORKDIR:-${DEFAULT_WORKDIR}}

export PYTHON=${PYTHON:-python3.12}
PYTHON_VERSION=$($PYTHON --version | cut -f2 -d' ')
export PYTHON_VERSION

# Set a default URL until we have our private one running.
export WHEEL_SERVER_URL=${WHEEL_SERVER_URL:-https://pypi.org/simple}

build_wheel() {
    local dist="$1"; shift
    local version="$1"; shift
    local artifacts_dir="$1"; shift

    # Build the base image.
    podman build \
       --tag e2e-build-base \
       -f "$SCRIPTDIR/Containerfile.e2e" \
       --build-arg="PYTHON=$PYTHON"

    # Create an image for building the wheel
    podman build -f "$SCRIPTDIR/Containerfile.e2e-one-wheel" \
           --tag "e2e-build-$dist" \
           --build-arg="DIST=$dist" \
           --build-arg="VERSION=$version" \
           --build-arg="WHEEL_SERVER_URL=$WHEEL_SERVER_URL"

    # Run the image to build the wheel.
    podman run -it \
           --name="e2e-build-$dist" \
           --replace \
           --network=none \
           --security-opt label=disable \
           -e "WHEEL_SERVER_URL=${WHEEL_SERVER_URL}" \
           "e2e-build-$dist"

    # Copy the results of the build out of the container, then clean up.
    mkdir -p "${artifacts_dir}"
    podman cp "e2e-build-$dist:/work-dir/built-artifacts.tar" "$artifacts_dir"
    podman rm "e2e-build-$dist"
    podman image rm "e2e-build-$dist"
}


usage() {
    cat - <<EOF
build_wheel.sh dist version
EOF
}


if [ $# -lt 2 ]; then
    usage
    exit 1
fi
DIST="$1"; shift
VERSION="$1"; shift
ARTIFACTS_DIR="${1:-artifacts}"

build_wheel "${DIST}" "${VERSION}" "${ARTIFACTS_DIR}"
