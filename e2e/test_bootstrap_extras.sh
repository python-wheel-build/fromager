#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests full bootstrap with packages that have extras.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

fromager \
  --log-file="$OUTDIR/test.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap -r "${SCRIPTDIR}/bootstrap_extras.txt"

find "$OUTDIR/wheels-repo/" -name '*.whl'
find "$OUTDIR/sdists-repo/" -name '*.tar.gz'
ls "$OUTDIR"/work-dir/*/build.log || true

UNEXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/stevedore-*.whl
$OUTDIR/sdists-repo/downloads/stevedore-*.tar.gz
$OUTDIR/sdists-repo/builds/stevedore-*.tar.gz
$OUTDIR/work-dir/stevedore-*/build.log
"

pass=true

for pattern in $UNEXPECTED_FILES; do
  if [ -f "${pattern}" ]; then
    echo "Found unexpected file $pattern" 1>&2
    pass=false
  fi
done

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/setuptools-*.whl
$OUTDIR/sdists-repo/downloads/setuptools-*.tar.gz
$OUTDIR/sdists-repo/builds/setuptools-*.tar.gz
$OUTDIR/work-dir/setuptools-*/build.log

$OUTDIR/wheels-repo/downloads/PySocks-*.whl
$OUTDIR/sdists-repo/downloads/PySocks-*.tar.gz
$OUTDIR/sdists-repo/builds/pysocks-*.tar.gz
$OUTDIR/work-dir/pysocks-*/build.log
"

for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find file $pattern" 1>&2
    pass=false
  fi
done

$pass
