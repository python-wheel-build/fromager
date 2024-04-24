#!/bin/bash

set -x
set -e
set -o pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

export PYTHON=${PYTHON:-python3.11}
PYTHON_VERSION=$($PYTHON --version | cut -f2 -d' ')
export PYTHON_VERSION

# Set a default URL until we have our private one running.
export WHEEL_SERVER_URL=${WHEEL_SERVER_URL:-https://pypi.org/simple}

build_wheel_isolated() {
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

build_wheel() {
    local dist="$1"; shift
    local version="$1"; shift
    local artifacts_dir="$1"; shift

    mkdir -p sdists-repo
    mkdir -p "${WORKDIR}"
    mkdir -p build-logs

    VENV="${WORKDIR}/venv"
    if [ -d "$VENV" ]; then
        # shellcheck disable=SC1091
        source "${VENV}/bin/activate"
    else
        "${PYTHON}" -m venv "${VENV}"
        # shellcheck disable=SC1091
        source "${VENV}/bin/activate"
        pip install --upgrade pip
        pip install -e .
    fi

    # Download the source archive
    python3 -m mirror_builder \
            --log-file build-logs/download-source-archive.log \
            --work-dir "$WORKDIR" \
            --sdists-repo sdists-repo \
            --wheels-repo wheels-repo \
            download-source-archive "${DIST}" "${VERSION}"

    # Prepare the source dir for building
    python3 -m mirror_builder \
            --log-file build-logs/prepare-source.log \
            --work-dir "$WORKDIR" \
            --sdists-repo sdists-repo \
            --wheels-repo wheels-repo \
            prepare-source "${DIST}" "${VERSION}"

    # Prepare the build environment
    python3 -m mirror_builder \
        --log-file build-logs/prepare-build.log \
        --work-dir "$WORKDIR" \
        --sdists-repo sdists-repo \
        --wheels-repo wheels-repo \
        --wheel-server-url "${WHEEL_SERVER_URL}" \
        prepare-build "${DIST}" "${VERSION}"

    # Build the wheel.
    python3 -m mirror_builder \
            --log-file build-logs/build.log \
            --wheel-server-url "$WHEEL_SERVER_URL" \
            --work-dir "$WORKDIR" \
            --sdists-repo sdists-repo \
            --wheels-repo wheels-repo \
            build "$DIST" "$VERSION"
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

DEFAULT_WORKDIR="$(pwd)/work-dir"
export WORKDIR=${WORKDIR:-${DEFAULT_WORKDIR}}

build_wheel "${DIST}" "${VERSION}" "${ARTIFACTS_DIR}"
