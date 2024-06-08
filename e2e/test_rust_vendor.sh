#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test to show we can build a single wheel, if the dependencies are
# available.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

set -x
set -e
set -o pipefail

# Bootstrap to create the build order file.
OUTDIR="$(dirname "$SCRIPTDIR")/e2e-output"

# What are we building?
DIST="maturin"
VERSION="1.6.0"

# Recreate output directory
rm -rf "$OUTDIR"
mkdir -p "$OUTDIR/build-logs"

# Set up virtualenv with the CLI and dependencies.
tox -e e2e -n -r
source ".tox/e2e/bin/activate"

# Bootstrap the test project
fromager \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/wheels-repo" \
    --work-dir="$OUTDIR/work-dir" \
    bootstrap "${DIST}==${VERSION}"

PYVER=$(python3 -c 'import sys; print("%s%s" % sys.version_info[:2])')

EXPECTED_FILES="
wheels-repo/downloads/${DIST}-${VERSION}-cp${PYVER}-cp${PYVER}-linux_x86_64.whl
sdists-repo/downloads/${DIST}-${VERSION}.tar.gz
"

pass=true
for f in $EXPECTED_FILES; do
  if [ ! -f "$OUTDIR/$f" ]; then
    echo "FAIL: Did not find $OUTDIR/$f" 1>&2
    pass=false
  fi
done
$pass
