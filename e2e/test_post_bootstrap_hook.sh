#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test post-bootstrap hook

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# What are we building?
DIST="setuptools"
VERSION="75.8.0"

# Install hook for test
pip install e2e/fromager_hooks

# Bootstrap the project
fromager \
  --debug \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/wheels-repo" \
    --work-dir="$OUTDIR/work-dir" \
    --settings-dir="$SCRIPTDIR/prebuilt_settings" \
    bootstrap "${DIST}==${VERSION}"



EXPECTED_FILES="
work-dir/test-output-file.txt
"

pass=true
for f in $EXPECTED_FILES; do
  if [ ! -f "$OUTDIR/$f" ]; then
    echo "FAIL: Did not find $OUTDIR/$f" 1>&2
    pass=false
  fi
done

cat $OUTDIR/work-dir/test-output-file.txt

if $pass; then
  if ! grep -q "${DIST}==${VERSION}" $OUTDIR/work-dir/test-output-file.txt; then
    echo "FAIL: Did not find content in post-bootstrap hook output file" 1>&2
    pass=false
  fi
fi

$pass
