#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test build-sequence (with and without skipping already built wheel)

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
    --settings-dir="$SCRIPTDIR/changelog_settings" \
    bootstrap "${DIST}==${VERSION}"

# Save the build order file but remove everything else.
cp "$OUTDIR/work-dir/build-order.json" "$OUTDIR/"
rm -rf "$OUTDIR/work-dir" "$OUTDIR/sdists-repo" "$OUTDIR/wheels-repo"

LOCAL_VERSION="fromager.e2e.test.1.0.cpu"

# Rebuild everything using the local version
log="$OUTDIR/build-logs/${DIST}-build.log"
fromager \
    --log-file "$log" \
    --work-dir "$OUTDIR/work-dir" \
    --sdists-repo "$OUTDIR/sdists-repo" \
    --wheels-repo "$OUTDIR/wheels-repo" \
    --settings-dir="$SCRIPTDIR/changelog_settings" \
    build-sequence \
    --force \
    --local-version "$LOCAL_VERSION" \
    "$OUTDIR/build-order.json"

find "$OUTDIR/wheels-repo/"

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/setuptools-*${LOCAL_VERSION}*.whl
$OUTDIR/wheels-repo/downloads/pbr-*${LOCAL_VERSION}*.whl
$OUTDIR/wheels-repo/downloads/stevedore-*${LOCAL_VERSION}*.whl

$OUTDIR/sdists-repo/downloads/stevedore-*.tar.gz
$OUTDIR/sdists-repo/downloads/setuptools-*.tar.gz
$OUTDIR/sdists-repo/downloads/pbr-*.tar.gz

$OUTDIR/work-dir/logs/stevedore-*.log
$OUTDIR/work-dir/logs/setuptools-*.log
$OUTDIR/work-dir/logs/pbr-*.log

$OUTDIR/work-dir/build-sequence-summary.md
$OUTDIR/work-dir/build-sequence-summary.json
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done
$pass

# Create an empty pip config file to bypass anything the user may have set.
export PIP_CONFIG_FILE="$OUTDIR/pip.conf"
touch "$PIP_CONFIG_FILE"

python3 -m virtualenv $OUTDIR/test_env
start_local_wheel_server
$OUTDIR/test_env/bin/python3 -m pip \
  -vvv \
  --disable-pip-version-check \
  install \
  --only-binary :all: \
  --no-cache-dir \
  --index-url "$WHEEL_SERVER_URL" \
  "${DIST}>=${VERSION}"
"$OUTDIR/test_env/bin/python3" -m pip freeze | tee "$OUTDIR/freeze.txt"

for package in stevedore pbr; do
  regex="${package}.*${LOCAL_VERSION}"
  if ! grep -q -E "${regex}" "$OUTDIR/freeze.txt"; then
    echo "Did not find $regex" 1>&2
    pass=false
  fi
done

$pass
