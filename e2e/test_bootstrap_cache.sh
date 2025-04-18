#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test bootstrap while taking advantage of the cache wheel server

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"
pass=true

DIST=setuptools
VER=78.1.0

################################################################################
# run fromager once to build wheels that can be used by a local wheel server

fromager \
  --debug \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  bootstrap "$DIST==$VER"

################################################################################
# run fromager again to verify that we pick up the existing wheels in the output directory

# Remove build work-dir and wheel server dir, but not the sdist or wheel repos
rm -rf "$OUTDIR/work-dir"
rm -rf "$OUTDIR/wheels-repo/simple"
rm "$OUTDIR/bootstrap.log"

fromager \
  --debug \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  bootstrap --cache-wheel-server-url="https://pypi.org/simple" "$DIST==$VER"

EXPECTED_LOG_MESSAGES=(
"$DIST: looking for existing wheel for version $VER with build tag () in"
"$DIST: found existing wheel"
)
for pattern in "${EXPECTED_LOG_MESSAGES[@]}"; do
  if ! grep -q "$pattern" "$OUTDIR/bootstrap.log"; then
    echo "FAIL: Did not find log message $pattern in $OUTDIR/bootstrap.log" 1>&2
    pass=false
  fi
done
$pass

UNEXPECTED_LOG_MESSAGES=(
"$DIST: checking if wheel was already uploaded to https://pypi.org/simple"
)

for pattern in "${UNEXPECTED_LOG_MESSAGES[@]}"; do
  if grep -q "$pattern" "$OUTDIR/bootstrap.log"; then
    echo "FAIL: Found log message $pattern in $OUTDIR/bootstrap.log" 1>&2
    pass=false
  fi
done
$pass

################################################################################

# run fromager with the cache wheel server pointing to the pypi server and
# verify we can pick it up from there

start_local_wheel_server
rm -rf "$OUTDIR/sdists-repo"
rm -rf "$OUTDIR/work-dir"
rm -rf "$OUTDIR/wheels-repo/build"
rm -rf "$OUTDIR/wheels-repo/download"
rm "$OUTDIR/bootstrap.log"

fromager \
  --debug \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  --no-cleanup \
  bootstrap --cache-wheel-server-url="https://pypi.org/simple" "$DIST==$VER"

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/setuptools-*.whl

$OUTDIR/work-dir/build-order.json
$OUTDIR/work-dir/constraints.txt
"

for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

$pass

UNEXPECTED_LOG_MESSAGES=(
"$DIST: loading build sdist dependencies from build-sdist-requirements.txt"
"$DIST: loading build backend dependencies from build-backend-requirements.txt"
"$DIST: loading build system dependencies from build-system-requirements.txt"
)

for pattern in "${UNEXPECTED_LOG_MESSAGES[@]}"; do
  echo $pattern
  if grep -q "$pattern" "$OUTDIR/bootstrap.log"; then
    echo "FAIL: found log message $pattern in $OUTDIR/bootstrap.log" 1>&2
    pass=false
  fi
done

$pass
