#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test to show that we get a detailed error message if a dependency is
# not available when setting up to build a package.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# What are we building?
DIST="stevedore"
VERSION="5.2.0"

# Bootstrap the test project
fromager \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/wheels-repo" \
    --work-dir="$OUTDIR/work-dir" \
    bootstrap "${DIST}==${VERSION}"

# Save the build order file but remove everything else.
cp "$OUTDIR/work-dir/build-order.json" "$OUTDIR/"
rm -r "$OUTDIR/work-dir" "$OUTDIR/sdists-repo" "$OUTDIR/wheels-repo"

# Rebuild the wheel mirror to be empty
pypi-mirror create -d "$OUTDIR/wheels-repo/downloads/" -m "$OUTDIR/wheels-repo/simple/"

start_local_wheel_server

# Define the function used in the build script
build_wheel() {
    local -r dist="$1"
    local -r version="$2"

    # Download the source archive
    fromager \
        --log-file "$OUTDIR/build-logs/${dist}-download-source-archive.log" \
        --work-dir "$OUTDIR/work-dir" \
        --sdists-repo "$OUTDIR/sdists-repo" \
        --wheels-repo "$OUTDIR/wheels-repo" \
        step download-source-archive "$dist" "$version" "https://pypi.org/simple"

    # Prepare the source dir for building
    fromager \
        --log-file "$OUTDIR/build-logs/${dist}-prepare-source.log" \
        --work-dir "$OUTDIR/work-dir" \
        --sdists-repo "$OUTDIR/sdists-repo" \
        --wheels-repo "$OUTDIR/wheels-repo" \
        step prepare-source "$dist" "$version"

    # Prepare the build environment
    fromager \
        --log-file "$OUTDIR/build-logs/${dist}-prepare-build.log" \
        --work-dir "$OUTDIR/work-dir" \
        --sdists-repo "$OUTDIR/sdists-repo" \
        --wheels-repo "$OUTDIR/wheels-repo" \
        --wheel-server-url "${WHEEL_SERVER_URL}" \
        step prepare-build "$dist" "$version"

    # Build an updated sdist
    fromager \
        --log-file "$OUTDIR/build-logs/${dist}-build-sdist.log" \
        --work-dir "$OUTDIR/work-dir" \
        --sdists-repo "$OUTDIR/sdists-repo" \
        --wheels-repo "$OUTDIR/wheels-repo" \
        step build-sdist "$dist" "$version"

    # Build the wheel
    fromager \
        --log-file "$OUTDIR/build-logs/${dist}-prepare-build.log" \
        --work-dir "$OUTDIR/work-dir" \
        --sdists-repo "$OUTDIR/sdists-repo" \
        --wheels-repo "$OUTDIR/wheels-repo" \
        --wheel-server-url "${WHEEL_SERVER_URL}" \
        step build-wheel "$dist" "$version"

    # Move the built wheel into place
    mv "$OUTDIR"/wheels-repo/build/*.whl "$OUTDIR/wheels-repo/downloads/"

    # update the wheel server
    pypi-mirror \
        create \
        -d "$OUTDIR/wheels-repo/downloads/" \
        -m "$OUTDIR/wheels-repo/simple/"

}

# Create and run a script to build everything, one wheel at a time.
#
# This is a little convoluted, but protects us from subshells
# swallowing any errors in individual steps like we would see if we
# passed the output of 'jq' to a while loop.
jq -r '.[] | "build_wheel " + .dist + " " + .version' \
   "$OUTDIR/build-order.json" \
   > "$OUTDIR/build.sh"
find "$OUTDIR/wheels-repo/"
source "$OUTDIR/build.sh"
find "$OUTDIR/wheels-repo/"

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/setuptools-*.whl
$OUTDIR/wheels-repo/downloads/pbr-*.whl
$OUTDIR/wheels-repo/downloads/stevedore-*.whl

$OUTDIR/sdists-repo/downloads/stevedore-*.tar.gz
$OUTDIR/sdists-repo/downloads/setuptools-*.tar.gz
$OUTDIR/sdists-repo/downloads/pbr-*.tar.gz

$OUTDIR/sdists-repo/builds/stevedore-*.tar.gz
$OUTDIR/sdists-repo/builds/setuptools-*.tar.gz
$OUTDIR/sdists-repo/builds/pbr-*.tar.gz
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

$pass
