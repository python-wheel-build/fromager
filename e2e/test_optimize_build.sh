#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

fromager \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --log-file="$OUTDIR/logfile.txt" \
  bootstrap 'stevedore==5.2.0'

pass=true

if  grep -q "have sdist version" "$OUTDIR/logfile.txt"; then
    echo "Failed to build source distribution"
    pass=false
fi

rm -rf "$OUTDIR/wheels-repo/downloads"
rm -rf "$OUTDIR/logfile.txt"

fromager \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --log-file="$OUTDIR/logfile.txt" \
  bootstrap 'stevedore==5.2.0'

if ! grep -q "have sdist version" "$OUTDIR/logfile.txt"; then
    echo "Building source distribution from scratch even after sdist exists"
    pass=false
fi

rm -rf "$OUTDIR/sdists-repo/builds"
rm -rf "$OUTDIR/wheels-repo/downloads"
rm -rf "$OUTDIR/logfile.txt"

fromager \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --log-file="$OUTDIR/logfile.txt" \
  bootstrap 'stevedore==5.2.0'

if  grep -q "have sdist version" "$OUTDIR/logfile.txt"; then
    echo "Failed to build source distribution"
    pass=false
fi

rm -rf "$OUTDIR/logfile.txt"
$pass
