#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test that the build order file produced by a bootstrap job gives us
# all of the dependencies that need to be built. Bootstrap a package,
# then use the build-order.json file rebuild those dependencies by
# only looking at a server that has content from that build-order.json
# file.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck disable=SC1091
source "${SCRIPTDIR}/common.sh"
TOPDIR="$( cd "${SCRIPTDIR}/.." && pwd )"

# Create the various output directories
mkdir -p "${WORKDIR}"
mkdir -p wheels-repo/downloads/
mkdir -p sdists-repo/downloads/

# What are we building?
TOPLEVEL=${1:-stevedore}

# Redirect stdout/stderr to logfile
logfile="$WORKDIR/rebuild-following-bootstrap.log"
exec > >(tee "$logfile") 2>&1

# Where does the wheel server run?
TEST_INDEX_NAME="test"
TEST_SERVER_DIR="$WORKDIR/devpi-server-dir"


bootstrap() {
  local dist="$1"; shift

  banner "Bootstrapping $dist"
  # Bootstrap a complex set of dependencies to get the build order. We
  # use a simple dist here instead of langchain to avoid dependencies
  # with rust parts so we can isolate the build environments when
  # building one wheel at a time later.
  podman build -f "${TOPDIR}/Containerfile.e2e-bootstrap" \
         --tag "e2e-bootstrap-$dist" \
         --build-arg="TOPLEVEL=$dist"

  # Create a container with the image so we can copy the
  # build-order.json file out of it to use for the build.
  podman create --name "e2e-extract-bootstrap-$dist" "e2e-bootstrap-$dist" ls >/dev/null 2>&1
  podman cp "e2e-extract-bootstrap-$dist:/work-dir/build-order.json" work-dir/
  podman rm -f "e2e-extract-bootstrap-$dist"
}

banner() {
  echo "##############################"
  echo "$*"
  echo "##############################"
}

build_wheel() {
  local dist="$1"; shift
  local version="$1"; shift

  "$TOPDIR/build_wheel.sh" -i -d "$dist" -v "$version" -a "work-dir/$dist"

  # Update the wheel server
  tar -C "work-dir/$dist" -xvf "work-dir/$dist/built-artifacts.tar"
  "$MIRROR_VENV/bin/devpi" upload --index "$TEST_INDEX_NAME" "work-dir/$dist/wheels-repo/build"/*.whl
}

on_exit() {
  [ "$HTTP_SERVER_PID" ] && kill "$HTTP_SERVER_PID"
}
trap on_exit EXIT SIGINT SIGTERM

# Build the base image.
banner "Build base image"
podman build \
       --tag e2e-build-base \
       -f "$TOPDIR/Containerfile.e2e" \
       --build-arg="PYTHON=$PYTHON"

# Bootstrap to create the build order file, if we don't have one.
if [ ! -f work-dir/build-order.json ]; then
  bootstrap "$TOPLEVEL"
fi

# Determine the primary IP of the host because podman won't see the
# devpi server via localhost.
IP=$(ip route get 1.1.1.1 | grep 1.1.1.1 | awk '{print $7}')
export WHEEL_SERVER_URL="http://${IP}:3141/root/${TEST_INDEX_NAME}/+simple/"
TEST_SERVER_BASE_URL="http://${IP}:3141"

# Set up a virtualenv with devpi
banner "Set up devpi"
MIRROR_VENV=$WORKDIR/venv-mirror
rm -rf "${MIRROR_VENV:?}"
python3 -m venv "$MIRROR_VENV"
"$MIRROR_VENV/bin/python3" -m pip install --index-url "$TOOL_SERVER_URL" devpi
rm -rf "${TEST_SERVER_DIR:?}"
"$MIRROR_VENV/bin/devpi-init" --serverdir "$TEST_SERVER_DIR" --no-root-pypi
"$MIRROR_VENV/bin/devpi-server" --host "${IP}" --serverdir "$TEST_SERVER_DIR" &
HTTP_SERVER_PID=$!

# Wait for the server to be available
tries=3
while [[ "$tries" -gt 0 ]]; do
  if curl "$TEST_SERVER_BASE_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# After the server is up, configure the index we will use.
"$MIRROR_VENV/bin/devpi" use "$TEST_SERVER_BASE_URL"
"$MIRROR_VENV/bin/devpi" login root --password ''  # not secured by default
"$MIRROR_VENV/bin/devpi" index --create "$TEST_INDEX_NAME"

# Create a script to build the wheels one at a time in the same
# order. We can't just read the output of jq in a loop because the
# container commands eat stdin.
jq -r '.[] | "build_wheel " + .dist + " " + .version' "work-dir/build-order.json" | tee "$WORKDIR/build_script.sh"
# shellcheck disable=SC1091
source "$WORKDIR/build_script.sh"

exit 0
