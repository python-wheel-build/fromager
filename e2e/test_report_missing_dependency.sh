#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test to show that we get a detailed error message if a dependency is
# not available when setting up to build a package.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

set -x
set -e
set -o pipefail

on_exit() {
  [ "$HTTP_SERVER_PID" ] && kill "$HTTP_SERVER_PID"
}
trap on_exit EXIT SIGINT SIGTERM

# Bootstrap to create the build order file.
OUTDIR="$(dirname "$SCRIPTDIR")/e2e-output"

# What are we building?
DIST="stevedore"
VERSION="5.2.0"

# Recreate output directory
rm -rf "$OUTDIR"
mkdir -p "$OUTDIR/build-logs"

tox -e e2e -n -r
source .tox/e2e/bin/activate

fromager \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap "${DIST}==${VERSION}"

# Extract the build dependencies from the bootstrap info.
jq -r '.[] | select( .type | contains("build-") ) | .req'  \
   "$OUTDIR/work-dir/build-order.json" > "$OUTDIR/expected_build_requirements.txt"

# Remove all of the build dependencies from the wheels-repo.
jq -r '.[] | select( .type | contains("build-") ) | .dist'  "$OUTDIR/work-dir/build-order.json" \
  | while read -r to_remove; do
  echo "Removing build dependency ${to_remove}"
  rm -f "$OUTDIR/wheels-repo/downloads/${to_remove}"*
done

# Rebuild the wheel mirror to only include the things we have not deleted.
rm -rf "$OUTDIR/wheels-repo/simple"
pypi-mirror create -d "$OUTDIR/wheels-repo/downloads/" -m "$OUTDIR/wheels-repo/simple/"

# Start a web server for the wheels-repo. We remember the PID so we
# can stop it later, and we determine the primary IP of the host
# because podman won't see the server via localhost.
python3 -m http.server --directory "$OUTDIR/wheels-repo/" 9999 &
HTTP_SERVER_PID=$!
IP=$(ip route get 1.1.1.1 | grep 1.1.1.1 | awk '{print $7}')
export WHEEL_SERVER_URL="http://${IP}:9999/simple"

# Rebuild the original toplevel wheel, expecting a failure.
version=$(jq -r '.[] | select ( .dist == "'$DIST'" ) | .version' "$OUTDIR/work-dir/build-order.json")

# Download the source archive
fromager \
  --log-file "$OUTDIR/build-logs/download-source-archive.log" \
  --work-dir "$OUTDIR/work-dir" \
  --sdists-repo "$OUTDIR/sdists-repo" \
  --wheels-repo "$OUTDIR/wheels-repo" \
  step download-source-archive "$DIST" "$VERSION" "https://pypi.org/simple"

# Prepare the source dir for building
fromager \
  --log-file "$OUTDIR/build-logs/prepare-source.log" \
  --work-dir "$OUTDIR/work-dir" \
  --sdists-repo "$OUTDIR/sdists-repo" \
  --wheels-repo "$OUTDIR/wheels-repo" \
  step prepare-source "$DIST" "$VERSION"

# Prepare the build environment
fromager \
  --log-file "$OUTDIR/build-logs/prepare-build.log" \
  --work-dir "$OUTDIR/work-dir" \
  --sdists-repo "$OUTDIR/sdists-repo" \
  --wheels-repo "$OUTDIR/wheels-repo" \
  --wheel-server-url "${WHEEL_SERVER_URL}" \
  step prepare-build "$DIST" "$VERSION" \
  || echo "Got expected build error"

if grep -q "MissingDependency" "$OUTDIR/build-logs/prepare-build.log"; then
  echo "PASS: Found expected error"
else
  echo "FAIL: Did not find expected error in $OUTDIR/build-logs/prepare-build.log"
  exit 1
fi

exit 0
