#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test meson build, verify that vendor_rust workaround is effective

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# What are we building?
DIST="meson"
VERSION="1.5.0"

# Bootstrap the test project
fromager \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/wheels-repo" \
    --work-dir="$OUTDIR/work-dir" \
    bootstrap "${DIST}==${VERSION}"

EXPECTED_FILES="
wheels-repo/downloads/${DIST}-${VERSION}-0-py3-none-any.whl
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
