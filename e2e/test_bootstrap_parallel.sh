#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests bootstrap parallel (bootstrap --sdist-only + build-parallel)

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# passing settings to bootstrap but should have 0 effect on it
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  bootstrap-parallel 'stevedore==5.2.0'

find "$OUTDIR/wheels-repo/" -name '*.whl'
find "$OUTDIR/sdists-repo/" -name '*.tar.gz'
ls "$OUTDIR"/work-dir/*/build.log || true

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

$OUTDIR/work-dir/build-order.json
$OUTDIR/work-dir/constraints.txt

$OUTDIR/bootstrap.log
$OUTDIR/fromager-errors.log

$OUTDIR/work-dir/pbr-*/build.log
$OUTDIR/work-dir/setuptools-*/build.log
$OUTDIR/work-dir/stevedore-*/build.log
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

$pass
