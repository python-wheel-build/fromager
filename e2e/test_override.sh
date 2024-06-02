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
pip install e2e/flit_core_override

fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap 'flit_core==3.9.0'

find "$OUTDIR/wheels-repo/simple/" -name '*.whl'

# Default to passing
pass=true

# Check for log message
if ! grep -q "using override to build flit_core wheel" "$OUTDIR/bootstrap.log"; then
    echo "FAIL: Did not find log message from override in $OUTDIR/bootstrap.log" 1>&2
    pass=false
fi

# Check for output files
EXPECTED_FILES="
wheels-repo/downloads/flit_core-3.9.0-py3-none-any.whl

sdists-repo/downloads/flit_core-3.9.0.tar.gz
"

for f in $EXPECTED_FILES; do
  if [ ! -f "$OUTDIR/$f" ]; then
    echo "FAIL: Did not find $f" 1>&2
    pass=false
  fi
done
$pass
