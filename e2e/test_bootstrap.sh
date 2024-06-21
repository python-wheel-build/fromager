#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests full bootstrap and installation of a complex package, without
# worrying about isolating the tools from upstream sources or
# restricting network access during the build. This allows us to test
# the overall logic of the build tools separately from the isolated
# build pipelines.

set -x
set -e
set -o pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
OUTDIR="$(dirname "$SCRIPTDIR")/e2e-output"

rm -rf "$OUTDIR"
mkdir "$OUTDIR"

tox -e e2e -n -r
source .tox/e2e/bin/activate

fromager \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap 'stevedore==5.2.0'

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

# Verify that the constraints file matches the build order file.
jq -r '.[] | .dist + "==" + .version' "$OUTDIR/work-dir/build-order.json" > "$OUTDIR/build-order-constraints.txt"
if ! diff "$OUTDIR/work-dir/constraints.txt" "$OUTDIR/build-order-constraints.txt";
then
  echo "FAIL: constraints do not match build order"
  pass=false
fi

$pass
