#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test to show we can build a single wheel, if the dependencies are
# available.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck disable=SC1091
source "$SCRIPTDIR/common.sh"

# What are we building?
DIST="maturin"
VERSION="1.6.0"

# Bootstrap the test project
fromager \
    $NETWORK_ISOLATION \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/wheels-repo" \
    --work-dir="$OUTDIR/work-dir" \
    bootstrap "${DIST}==${VERSION}"

PYVER=$(python3 -c 'import sys; print("%s%s" % sys.version_info[:2])')

EXPECTED_FILES="
wheels-repo/downloads/${DIST}-${VERSION}-0-cp${PYVER}-cp${PYVER}-${WHEEL_PLATFORM_TAG}.whl
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
