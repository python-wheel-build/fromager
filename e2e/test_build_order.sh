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

start_local_wheel_server

# copy sdists to wheel-repo/download so that it can be put on local pypi index server (even later when fromager calls update_wheel_mirror)
rm -r "$OUTDIR/wheels-repo" "$OUTDIR/work-dir"
mkdir -p "$OUTDIR/wheels-repo/downloads"

# IMPORTANT: cp -r behaves differently on macos: adding a trailing / to the src directory will end up copying the contents of that directory
cp -r "$OUTDIR/sdists-repo/downloads" "$OUTDIR/wheels-repo/"
rm -r "$OUTDIR/sdists-repo"

pypi-mirror create -c -d "$OUTDIR/wheels-repo/downloads/" -m "$OUTDIR/wheels-repo/simple/"

# Rebuild everything
log="$OUTDIR/build-logs/${DIST}-build.log"
fromager \
    --log-file "$log" \
    --work-dir "$OUTDIR/work-dir" \
    --sdists-repo "$OUTDIR/sdists-repo" \
    --wheels-repo "$OUTDIR/wheels-repo" \
    --settings-dir="$SCRIPTDIR/changelog_settings" \
    build-sequence "$OUTDIR/build-order.json"

find "$OUTDIR/wheels-repo/"

if grep -q "skipping building wheels for stevedore" "$log"; then
  echo "Found message indicating build of stevedore was skipped" 1>&2
  pass=false
fi

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/setuptools-*.whl
$OUTDIR/wheels-repo/downloads/pbr-*.whl
$OUTDIR/wheels-repo/downloads/stevedore-*.whl

$OUTDIR/sdists-repo/downloads/stevedore-*.tar.gz
$OUTDIR/sdists-repo/downloads/setuptools-*.tar.gz
$OUTDIR/sdists-repo/downloads/pbr-*.tar.gz
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

$pass

# Rebuild everything with the skip flag and verify we reuse the existing wheels
log="$OUTDIR/build-logs/${DIST}-build-skip.log"
fromager \
    --wheel-server-url $WHEEL_SERVER_URL \
    --log-file "$log" \
    --work-dir "$OUTDIR/work-dir" \
    --sdists-repo "$OUTDIR/sdists-repo" \
    --wheels-repo "$OUTDIR/wheels-repo" \
    --settings-dir="$SCRIPTDIR/changelog_settings" \
    build-sequence --skip-existing "$OUTDIR/build-order.json"

find "$OUTDIR/wheels-repo/"

if ! grep -q "skipping builds for versions of packages available" "$log"; then
  echo "Did not find message indicating builds would be skipped" 1>&2
  pass=false
fi
if ! grep -q "skipping building wheels for stevedore" "$log"; then
  echo "Did not find message indicating build of stevedore was skipped" 1>&2
  pass=false
fi

$pass

# Rebuild everything with the skip env var and verify we reuse the existing wheels
export FROMAGER_BUILD_SEQUENCE_SKIP_EXISTING=true
log="$OUTDIR/build-logs/${DIST}-build-skip-env.log"
fromager \
    --wheel-server-url $WHEEL_SERVER_URL \
    --log-file "$log" \
    --work-dir "$OUTDIR/work-dir" \
    --sdists-repo "$OUTDIR/sdists-repo" \
    --wheels-repo "$OUTDIR/wheels-repo" \
    --settings-dir="$SCRIPTDIR/changelog_settings" \
    build-sequence "$OUTDIR/build-order.json"

find "$OUTDIR/wheels-repo/"

if ! grep -q "skipping builds for versions of packages available" "$log"; then
  echo "Did not find message indicating builds would be skipped" 1>&2
  pass=false
fi
if ! grep -q "skipping building wheels for stevedore" "$log"; then
  echo "Did not find message indicating build of stevedore was skipped" 1>&2
  pass=false
fi

$pass

# bootstrap stevedore with 2 changelog.
log="$OUTDIR/build-logs/${DIST}-build-changelog.log"
fromager \
    --wheel-server-url $WHEEL_SERVER_URL \
    --log-file "$log" \
    --work-dir "$OUTDIR/work-dir" \
    --sdists-repo "$OUTDIR/sdists-repo" \
    --wheels-repo "$OUTDIR/wheels-repo" \
    --settings-dir="$SCRIPTDIR/changelog_settings-2" \
    build-sequence --skip-existing "$OUTDIR/build-order.json"

find "$OUTDIR/wheels-repo/"

if grep -q "skipping building wheels for stevedore" "$log"; then
  echo "Found message indicating build of stevedore was skipped" 1>&2
  pass=false
fi

find "$OUTDIR/wheels-repo/"

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/stevedore-5.2.0-2*.whl

$OUTDIR/sdists-repo/downloads/stevedore-*.tar.gz
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

$pass
