#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests bootstrap with --skip-constraints option to verify constraints.txt is not generated
# and build-order.json is still created.
# The resulting packages should still be built and available in the
# wheels and sdists repositories.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap --skip-constraints 'stevedore==5.2.0'

find "$OUTDIR/wheels-repo/" -name '*.whl'
find "$OUTDIR/sdists-repo/" -name '*.tar.gz'
ls "$OUTDIR"/work-dir/*/build.log || true

if [ -f "$OUTDIR/work-dir/constraints.txt" ]; then
  echo "FAIL: constraints.txt was created despite --skip-constraints flag" 1>&2
  exit 1
fi

if [ ! -f "$OUTDIR/work-dir/build-order.json" ]; then
  echo "FAIL: build-order.json was not created" 1>&2
  exit 1
fi

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/setuptools-*.whl
$OUTDIR/wheels-repo/downloads/pbr-*.whl
$OUTDIR/wheels-repo/downloads/stevedore-*.whl

$OUTDIR/sdists-repo/downloads/stevedore-*.tar.gz
$OUTDIR/sdists-repo/downloads/setuptools-*.tar.gz
$OUTDIR/sdists-repo/downloads/pbr-*.tar.gz

$OUTDIR/work-dir/build-order.json

$OUTDIR/bootstrap.log
$OUTDIR/fromager-errors.log
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

if ! grep -q "skipping constraints.txt generation as requested" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: Did not find log message indicating constraints.txt generation was skipped" 1>&2
  pass=false
fi

$pass
