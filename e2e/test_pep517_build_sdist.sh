#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test to show that we get a detailed error message if a dependency is
# not available when setting up to build a package.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# What are we building?
DIST="stevedore"
VERSION="5.2.0"

pip install e2e/stevedore_override

# Download the source archive
fromager \
    --log-file "$OUTDIR/build-logs/${DIST}-download-source-archive.log" \
    --work-dir "$OUTDIR/work-dir" \
    --sdists-repo "$OUTDIR/sdists-repo" \
    --wheels-repo "$OUTDIR/wheels-repo" \
    step download-source-archive "$DIST" "$VERSION" "https://pypi.org/simple"

# Prepare the source dir for building
rm -rf "$OUTDIR/work-dir/${DIST}*"
fromager \
    --log-file "$OUTDIR/build-logs/${DIST}-prepare-source.log" \
    --work-dir "$OUTDIR/work-dir" \
    --sdists-repo "$OUTDIR/sdists-repo" \
    --wheels-repo "$OUTDIR/wheels-repo" \
    step prepare-source "$DIST" "$VERSION"

# Prepare the build environment
fromager \
    --log-file "$OUTDIR/build-logs/${DIST}-prepare-build.log" \
    --work-dir "$OUTDIR/work-dir" \
    --sdists-repo "$OUTDIR/sdists-repo" \
    --wheels-repo "$OUTDIR/wheels-repo" \
    --wheel-server-url "https://pypi.org/simple/" \
    step prepare-build "$DIST" "$VERSION"

# Build an updated sdist
rm -rf "$OUTDIR/sdists-repo/builds"
fromager \
    --log-file "$OUTDIR/build-logs/${DIST}-build-sdist.log" \
    --work-dir "$OUTDIR/work-dir" \
    --sdists-repo "$OUTDIR/sdists-repo" \
    --wheels-repo "$OUTDIR/wheels-repo" \
    step build-sdist "$DIST" "$VERSION"

EXPECTED_FILES="
$OUTDIR/sdists-repo/builds/stevedore-*.tar.gz
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

$pass
