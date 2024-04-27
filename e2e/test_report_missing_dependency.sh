#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck disable=SC1091
source "${SCRIPTDIR}/common.sh"
TOPDIR="$( cd "${SCRIPTDIR}/.." && pwd )"

# Create the various output directories
mkdir -p "${WORKDIR}"
mkdir -p wheels-repo/downloads/
mkdir -p sdists-repo/downloads/

# What are we building?
TOPLEVEL=stevedore

# Redirect stdout/stderr to logfile
logfile="$WORKDIR/report-missing-dependency.log"
exec > >(tee "$logfile") 2>&1

on_exit() {
  [ "$HTTP_SERVER_PID" ] && kill "$HTTP_SERVER_PID"
}
trap on_exit EXIT SIGINT SIGTERM

# Bootstrap to create the build order file, if we don't have one.
if [ ! -f work-dir/build-order.json ]; then
    "$TOPDIR/mirror-sdists.sh" "$TOPLEVEL"
fi

# Extract the build dependencies from the bootstrap info.
jq -r '.[] | select( .type | contains("build_") ) | .req'  "$WORKDIR/build-order.json" > "$WORKDIR/expected_build_requirements.txt"

# Remove all of the build dependencies from the wheels-repo.
jq -r '.[] | select( .type | contains("build_") ) | .dist'  "$WORKDIR/build-order.json" \
   | while read -r to_remove; do
    echo "Removing build dependency ${to_remove}"
    rm -f "wheels-repo/downloads/${to_remove}"*
done

# Start a web server for the wheels-repo. We remember the PID so we
# can stop it later, and we determine the primary IP of the host
# because podman won't see the server via localhost.
$PYTHON -m http.server --directory wheels-repo/ 9090 &
HTTP_SERVER_PID=$!
IP=$(ip route get 1.1.1.1 | grep 1.1.1.1 | awk '{print $7}')
export WHEEL_SERVER_URL="http://${IP}:9090/simple"

# Set up a virtualenv with the mirror tool in it.
banner "Set up mirror tools"
MIRROR_VENV=$WORKDIR/venv-mirror-tools
rm -rf "${MIRROR_VENV:?}"
python3 -m venv "$MIRROR_VENV"
"$MIRROR_VENV/bin/python3" -m pip install --index-url "$TOOL_SERVER_URL" python-pypi-mirror
rm -rf wheels-repo/simple
"$MIRROR_VENV/bin/pypi-mirror" create -d wheels-repo/downloads/ -m wheels-repo/simple/

# Rebuild the original toplevel wheel, expecting a failure.
version=$(jq -r '.[] | select ( .dist == "'$TOPLEVEL'" ) | .version' "$WORKDIR/build-order.json")
"${TOPDIR}/build_wheel.sh" "$TOPLEVEL" "$version" "$WORKDIR" || echo "Got expected build error"

if grep -q MissingDependency "build-logs/prepare-build.log"; then
    echo "Found expected error"
else
    echo "Did not find expected error in build-logs/prepare-build.log"
    exit 1
fi

exit 0
