#!/bin/bash

set -x
set -e
set -o pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "${SCRIPTDIR}/common.sh"
TOPDIR="$( cd "${SCRIPTDIR}/.." && pwd )"

# Where should the test write working files
WORKDIR=$(pwd)/work-dir

# Create the various output directories
mkdir -p $WORKDIR
mkdir -p wheels-repo
mkdir -p sdists-repo

# Redirect stdout/stderr to logfile
logfile="$WORKDIR/mirror-sdists-${PYTHON_VERSION}.log"
exec > >(tee "$logfile") 2>&1

# Which version of python should the test use
PYTHON=${PYTHON:-python3.12}

# What image tag should be used
TAG=$(basename ${BASH_SOURCE[0]} .sh)

# How do we run something inside a container
in_container() {
    podman run -it --rm \
           -e PYTHON=$PYTHON \
           -e WORKDIR=/work-dir \
           -e VERBOSE=$VERBOSE \
           --userns=keep-id \
           --security-opt label=disable \
           --volume $WORKDIR:/work-dir:rw,exec \
           --volume $(pwd)/wheels-repo:/wheels-repo:rw \
           --volume $(pwd)/sdists-repo:/sdists-repo:rw \
           --volume .:/src:rw,exec \
           $TAG \
           ./e2e/container_exec.sh "$@"
}

in_isolated_container() {
    podman run -it --rm \
           -e PYTHON=$PYTHON \
           -e WORKDIR=/work-dir \
           -e VERBOSE=true \
           --network=none \
           --userns=keep-id \
           --security-opt label=disable \
           --volume $WORKDIR:/work-dir:rw,exec \
           --volume $(pwd)/wheels-repo:/wheels-repo:rw \
           --volume $(pwd)/sdists-repo:/sdists-repo:rw \
           --volume .:/src:rw,exec \
           $TAG \
           ./e2e/container_exec.sh "$@"
}

# Build the image.
podman build --tag $TAG -f $TOPDIR/Containerfile.e2e

# Bootstrap a complex set of dependencies to get the build order. We
# use a simple dist here instead of langchain to avoid dependencies
# with rust parts so we can isolate the build environments when
# building one wheel at a time later.
in_container bootstrap "stevedore"

VERBOSE=true

BOOTSTRAP_OUTPUT=$WORKDIR/bootstrap-output.txt
find wheels-repo/downloads > $BOOTSTRAP_OUTPUT

# Look at the bootstrap command output to decide which wheels to build.
REBUILD_ORDER_FILE=${WORKDIR}/build-order.json

# Recreate sdists-repo and wheels-repo so they are rebuilt as we build
# those wheels again.
rm -rf wheels-repo sdists-repo
mkdir -p wheels-repo
mkdir -p wheels-repo/downloads/
mkdir -p sdists-repo

# Set up a virtualenv with the mirror tool in it.
VENV=$WORKDIR/venv-mirror-tools
python3 -m venv $VENV
$VENV/bin/python3 -m pip install python-pypi-mirror

build_wheel() {
    local name="$1"; shift
    local version="$1"; shift

    in_container download-source-archive "$name" "$version" 2>&1 | tee $WORKDIR/download-source-archive-$name.log
    source_filename=$(cat $WORKDIR/last-download.txt)

    in_container prepare-source "$name" "$version" "$source_filename" 2>&1 | tee $WORKDIR/prepare-source-$name.log
    source_directory=$(cat $WORKDIR/last-source-dir.txt)

    in_container prepare-build "$name" "$version" "$source_directory" 2>&1 | tee $WORKDIR/prepare-build-$name.log

    # TODO: Different container files for building different packages
    in_isolated_container build "$name" "$version" "$source_directory" 2>&1 | tee $WORKDIR/build-$name.log

    # Update the wheel server directory so the next build can find its dependencies.
    for wheel_filename in $(cat $WORKDIR/last-wheels.txt); do
        cp ./${wheel_filename} wheels-repo/downloads/
        $VENV/bin/pypi-mirror create -d wheels-repo/downloads/ -m wheels-repo/simple/
    done
}

# Create a script to build the wheels one at a time in the same
# order. We can't just read the output of jq in a loop because the
# container commands eat stdin.
jq -r '.[] | "build_wheel " + .dist + " " + .version' "${REBUILD_ORDER_FILE}" > $WORKDIR/build_script.sh
source $WORKDIR/build_script.sh

BUILD_ONE_OUTPUT=$WORKDIR/build-one-output.txt
find wheels-repo/downloads > $BUILD_ONE_OUTPUT

# We should get the same results
if diff $BOOTSTRAP_OUTPUT $BUILD_ONE_OUTPUT; then
    echo "The output is the same"
fi
