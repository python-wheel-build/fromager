#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test bootstrap while taking advantage of the cache wheel server

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"
pass=true

# run fromager once to build wheels that can be used by a local wheel server
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  bootstrap 'setuptools'

start_local_wheel_server
rm -rf "$OUTDIR/sdists-repo"
rm -rf "$OUTDIR/work-dir"
rm "$OUTDIR/bootstrap.log"


# run fromager with the cache wheel server pointing to the local wheel server
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  --no-cleanup \
  bootstrap --cache-wheel-server-url=$WHEEL_SERVER_URL 'setuptools'

EXPECTED_LOG_MESSAGES=(
"setuptools: loading build sdist dependencies from build-sdist-requirements.txt"
"setuptools: loading build backend dependencies from build-backend-requirements.txt"
"setuptools: loading build system dependencies from build-system-requirements.txt"
)

for pattern in "${EXPECTED_LOG_MESSAGES[@]}"; do
  echo $pattern
  if ! grep -q "$pattern" "$OUTDIR/bootstrap.log"; then
    echo "FAIL: Did not find log message $pattern in $OUTDIR/bootstrap.log" 1>&2
    pass=false
  fi
done

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/setuptools-*.whl

$OUTDIR/work-dir/setuptools-*/*-requirements.txt

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

rm -rf "$OUTDIR/sdists-repo"
rm -rf "$OUTDIR/work-dir"
rm -rf "$OUTDIR/wheels-repo"
rm "$OUTDIR/bootstrap.log"

# run fromager with the cache wheel server pointing to the pypi server
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  --no-cleanup \
  bootstrap --cache-wheel-server-url="https://pypi.org/simple" 'setuptools'

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

for pattern in "${EXPECTED_LOG_MESSAGES[@]}"; do
  echo $pattern
  if grep -q "$pattern" "$OUTDIR/bootstrap.log"; then
    echo "FAIL: found log message $pattern in $OUTDIR/bootstrap.log" 1>&2
    pass=false
  fi
done

$pass
