#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test to show that we get a detailed error message if a dependency is
# not available when setting up to build a package.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# What are we building?
DIST="stevedore"
VERSION="5.2.0"

fromager \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap "${DIST}==${VERSION}"

# Extract the build dependencies from the bootstrap info.
jq -r '.[] | .edges | .[] | select( .req_type | contains("build-") ) | .req'  \
   "$OUTDIR/work-dir/graph.json" > "$OUTDIR/expected_build_requirements.txt"

# Remove all of the build dependencies from the wheels-repo.
jq -r '.[] | .edges | .[] | select( .req_type | contains("build-") ) | .key | split("==")[0]'  "$OUTDIR/work-dir/graph.json" \
  | while read -r to_remove; do
  echo "Removing build dependency ${to_remove}"
  rm -f "$OUTDIR/wheels-repo/downloads/${to_remove}"*
done

# Rebuild the wheel mirror to only include the things we have not deleted.
rm -rf "$OUTDIR/wheels-repo/simple"
pypi-mirror create -d "$OUTDIR/wheels-repo/downloads/" -m "$OUTDIR/wheels-repo/simple/"

start_local_wheel_server

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
build_log="$OUTDIR/build-logs/prepare-build.log"
fromager \
  --log-file "$build_log" \
  --work-dir "$OUTDIR/work-dir" \
  --sdists-repo "$OUTDIR/sdists-repo" \
  --wheels-repo "$OUTDIR/wheels-repo" \
  --wheel-server-url "${WHEEL_SERVER_URL}" \
  step prepare-build "$DIST" "$VERSION" \
  || echo "Got expected build error"

if grep -q "MissingDependency" "$build_log"; then
  echo "PASS: Found expected error"
else
  echo "FAIL: Did not find expected error in $build_log"
  cat "$build_log"
  exit 1
fi

exit 0
