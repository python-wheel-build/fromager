#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test with simple C extension module and non-normalized package

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck disable=SC1091
source "$SCRIPTDIR/common.sh"

# What are we building?
DIST="MarkupSafe"
VERSION="2.1.5"

# Bootstrap the test project
fromager \
    $NETWORK_ISOLATION \
    --verbose \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/wheels-repo" \
    --work-dir="$OUTDIR/work-dir" \
    bootstrap "${DIST}==${VERSION}"

PYVER=$(python3 -c 'import sys; print("%s%s" % sys.version_info[:2])')

EXTRACTDIR="$OUTDIR/extract"
mkdir -p "$EXTRACTDIR"

WHL=wheels-repo/downloads/${DIST}-${VERSION}-0-cp${PYVER}-cp${PYVER}-${WHEEL_PLATFORM_TAG}.whl
unzip "$OUTDIR/$WHL" -d "$EXTRACTDIR"

DIST_INFO="extract/${DIST}-${VERSION}.dist-info"

EXPECTED_FILES="
$WHL
sdists-repo/downloads/${DIST}-${VERSION}.tar.gz
$DIST_INFO/fromager-build-backend-requirements.txt
$DIST_INFO/fromager-build-sdist-requirements.txt
$DIST_INFO/fromager-build-settings
$DIST_INFO/fromager-build-system-requirements.txt
"

if [ "$HAS_ELFDEP" = "1" ]; then
    EXPECTED_FILES="
$EXPECTED_FILES
$DIST_INFO/fromager-elf-requires.txt
"
fi

pass=true
for f in $EXPECTED_FILES; do
  if [ ! -f "$OUTDIR/$f" ]; then
    echo "FAIL: Did not find $OUTDIR/$f" 1>&2
    pass=false
  fi
done
$pass
