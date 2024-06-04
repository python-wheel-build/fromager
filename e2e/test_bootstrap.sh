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

find "$OUTDIR/wheels-repo/simple/" -name '*.whl'

EXPECTED_FILES="
wheels-repo/downloads/flit_core-3.9.0-py3-none-any.whl
wheels-repo/downloads/wheel-0.43.0-py3-none-any.whl
wheels-repo/downloads/setuptools-70.0.0-py3-none-any.whl
wheels-repo/downloads/pbr-6.0.0-py2.py3-none-any.whl
wheels-repo/downloads/stevedore-5.2.0-py3-none-any.whl

sdists-repo/downloads/stevedore-5.2.0.tar.gz
sdists-repo/downloads/setuptools-70.0.0.tar.gz
sdists-repo/downloads/wheel-0.43.0.tar.gz
sdists-repo/downloads/flit_core-3.9.0.tar.gz
sdists-repo/downloads/pbr-6.0.0.tar.gz

work-dir/build-order.json
work-dir/constraints.txt

work-dir/flit_core-3.9.0/build.log
work-dir/pbr-6.0.0/build.log
work-dir/setuptools-70.0.0/build.log
work-dir/stevedore-5.2.0/build.log
work-dir/wheel-0.43.0/build.log
"

pass=true
for f in $EXPECTED_FILES; do
  if [ ! -f "$OUTDIR/$f" ]; then
    echo "Did not find $f" 1>&2
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
