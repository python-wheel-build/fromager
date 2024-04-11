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
mkdir -p wheels-repo/downloads/
mkdir -p sdists-repo/downloads/

# Redirect stdout/stderr to logfile
logfile="$WORKDIR/rebuild-following-bootstrap.log"
exec > >(tee "$logfile") 2>&1

# Which version of python should the test use
PYTHON=${PYTHON:-python3.12}

bootstrap() {
    local dist="$1"; shift

    banner "Bootstrapping $dist"
    # Bootstrap a complex set of dependencies to get the build order. We
    # use a simple dist here instead of langchain to avoid dependencies
    # with rust parts so we can isolate the build environments when
    # building one wheel at a time later.
    podman build -f $TOPDIR/Containerfile.e2e-bootstrap \
           --tag e2e-bootstrap-$dist \
           --build-arg="TOPLEVEL=$dist"

    # Create a container with the image so we can copy the
    # build-order.json file out of it to use for the build.
    podman rm -f e2e-extract-bootstrap-$dist
    podman create --name e2e-extract-bootstrap-$dist e2e-bootstrap-$dist ls >/dev/null 2>&1
    podman cp e2e-extract-bootstrap-$dist:/bootstrap/build-order.json work-dir/
}

banner() {
    echo "##############################"
    echo "$*"
    echo "##############################"
}

build_wheel() {
    local dist="$1"; shift
    local version="$1"; shift

    banner " building image for $dist $version"

    # Create an image for building the wheel
    podman build -f $TOPDIR/Containerfile.e2e-one-wheel \
           --tag e2e-build-$dist \
           --build-arg="DIST=$dist" \
           --build-arg="VERSION=$version" \
           --build-arg="WHEEL_SERVER_URL=$WHEEL_SERVER_URL"

    banner " building $dist $version"

    podman rm -f e2e-build-$dist
    podman run -it \
           --name=e2e-build-$dist \
           --network=none \
           --security-opt label=disable \
           -e WHEEL_SERVER_URL=${WHEEL_SERVER_URL} \
           e2e-build-$dist

    # Copy the results of the build out of the container, then clean up.
    mkdir -p work-dir/$dist
    podman cp e2e-build-$dist:/work-dir/built-artifacts.tar work-dir/$dist
    podman rm e2e-build-$dist

    # Update the wheel server directory so the next build can find its dependencies.
    tar -C work-dir/$dist -xvf work-dir/$dist/built-artifacts.tar
    cp work-dir/$dist/wheels-repo/build/*.whl wheels-repo/downloads/
    cp work-dir/$dist/sdists-repo/downloads/*.tar.gz sdists-repo/downloads/
    $MIRROR_VENV/bin/pypi-mirror create -d wheels-repo/downloads/ -m wheels-repo/simple/
}

on_exit() {
  [ "$HTTP_SERVER_PID" ] && kill $HTTP_SERVER_PID
}
trap on_exit EXIT SIGINT SIGTERM

# Build the base image.
banner "Build base image"
podman build --tag e2e-build-base -f $TOPDIR/Containerfile.e2e

# Bootstrap to create the build order file, if we don't have one.
if [ ! -f work-dir/build-order.json ]; then
    bootstrap stevedore
fi

# Start a web server for the wheels-repo. We remember the PID so we
# can stop it later, and we determine the primary IP of the host
# because podman won't see the server via localhost.
$PYTHON -m http.server --directory wheels-repo/ 9090 &
HTTP_SERVER_PID=$!
IP=$(ip route get 1.1.1.1 | grep 1.1.1.1 | awk '{print $7}')
WHEEL_SERVER_URL="http://${IP}:9090/simple"

# Set up a virtualenv with the mirror tool in it.
banner "Set up mirror tools"
MIRROR_VENV=$WORKDIR/venv-mirror-tools
rm -rf $MIRROR_VENV/
python3 -m venv $MIRROR_VENV
$MIRROR_VENV/bin/python3 -m pip install python-pypi-mirror

# Create a script to build the wheels one at a time in the same
# order. We can't just read the output of jq in a loop because the
# container commands eat stdin.
jq -r '.[] | "build_wheel " + .dist + " " + .version' "work-dir/build-order.json" | tee $WORKDIR/build_script.sh
source $WORKDIR/build_script.sh

exit 0

# Bootstrap a complex set of dependencies to get the build order. We
# use a simple dist here instead of langchain to avoid dependencies
# with rust parts so we can isolate the build environments when
# building one wheel at a time later.
in_container e2e-build-base bootstrap "stevedore"

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
