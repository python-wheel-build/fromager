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
  bootstrap 'stevedore==5.2.0'

start_local_wheel_server
rm -rf "$OUTDIR/sdists-repo"
rm -rf "$OUTDIR/work-dir"

# run fromager with the cache wheel server pointing to the local wheel server
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  --no-cleanup \
  bootstrap --cache-wheel-server-url=$WHEEL_SERVER_URL 'stevedore==5.2.0'

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/setuptools-*.whl
$OUTDIR/wheels-repo/downloads/pbr-*.whl
$OUTDIR/wheels-repo/downloads/stevedore-*.whl

$OUTDIR/sdists-repo/downloads/stevedore-*.tar.gz
$OUTDIR/sdists-repo/downloads/setuptools-*.tar.gz
$OUTDIR/sdists-repo/downloads/pbr-*.tar.gz

$OUTDIR/work-dir/pbr-*/pbr-*/pbr-*.dist-info/fromager-*.txt
$OUTDIR/work-dir/setuptools-*/setuptools-*/setuptools-*.dist-info/fromager-*.txt
$OUTDIR/work-dir/stevedore-*/stevedore-*/stevedore-*.dist-info/fromager-*.txt

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

# run fromager with the cache wheel server pointing to the pypi server
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  --no-cleanup \
  bootstrap --cache-wheel-server-url="https://pypi.org/simple" 'stevedore==5.2.0'

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/setuptools-*.whl
$OUTDIR/wheels-repo/downloads/pbr-*.whl
$OUTDIR/wheels-repo/downloads/stevedore-*.whl

$OUTDIR/sdists-repo/downloads/stevedore-*.tar.gz
$OUTDIR/sdists-repo/downloads/setuptools-*.tar.gz
$OUTDIR/sdists-repo/downloads/pbr-*.tar.gz

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

NOT_EXPECTED_FILES="
$OUTDIR/work-dir/pbr-*/pbr-*/pbr-*.dist-info/fromager-*.txt
$OUTDIR/work-dir/setuptools-*/setuptools-*/setuptools-*.dist-info/fromager-*.txt
$OUTDIR/work-dir/stevedore-*/stevedore-*/stevedore-*.dist-info/fromager-*.txt
"

for pattern in $NOT_EXPECTED_FILES; do
  if [ -f "${pattern}" ]; then
    echo "Found $pattern" 1>&2
    pass=false
  fi
done

$pass

EXPECTED_DIR="
$OUTDIR/work-dir/pbr-*/pbr-*/pbr-*.dist-info
$OUTDIR/work-dir/setuptools-*/setuptools-*/setuptools-*.dist-info
$OUTDIR/work-dir/stevedore-*/stevedore-*/stevedore-*.dist-info
"

for pattern in $EXPECTED_DIR; do
  if [ -d "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

$pass
