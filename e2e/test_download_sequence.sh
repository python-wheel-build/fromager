#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests downloading source for an entire `build-order.json` via
# sources.download_source.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Bootstrap the test project
fromager \
  -v \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  download-sequence \
  "$SCRIPTDIR/download_sequence/simplejson-build-order.json" \
  "https://pypi.org/simple"

pass=true

# Check for output files
EXPECTED_FILES="
sdists-repo/downloads/flit_core-3.9.0.tar.gz
sdists-repo/downloads/setuptools-70.0.0.tar.gz
sdists-repo/downloads/simplejson-3.19.2.tar.gz
sdists-repo/downloads/wheel-0.43.0.tar.gz
"

pass=true
for f in $EXPECTED_FILES; do
  if [ ! -f "$OUTDIR/$f" ]; then
    echo "FAIL: Did not find $OUTDIR/$f" 1>&2
    pass=false
  fi
done
echo $pass
$pass
