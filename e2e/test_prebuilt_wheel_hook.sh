#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test build-sequence prebuilt-wheel hook

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# What are we building?
DIST="setuptools"
VERSION="75.8.0"

# Install hook for test
pip install e2e/fromager_hooks

# Bootstrap the test project
fromager \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/wheels-repo" \
    --work-dir="$OUTDIR/work-dir" \
    --settings-dir="$SCRIPTDIR/prebuilt_settings" \
    bootstrap "${DIST}==${VERSION}"

# Save the build order file but remove everything else.
cp "$OUTDIR/work-dir/build-order.json" "$OUTDIR/"

# Remove downloaded wheels to trigger hook
rm -rf "$OUTDIR/wheels-repo"

log="$OUTDIR/build-logs/${DIST}-build.log"
fromager \
    --log-file "$log" \
    --work-dir "$OUTDIR/work-dir" \
    --sdists-repo "$OUTDIR/sdists-repo" \
    --wheels-repo "$OUTDIR/wheels-repo" \
    --settings-dir="$SCRIPTDIR/prebuilt_settings" \
    build-sequence "$OUTDIR/build-order.json"

if ! grep -q "downloading prebuilt wheel ${DIST}==${VERSION}" "$log"; then
  echo "Lack of message indicating download of prebuilt wheel" 1>&2
  pass=false
fi


EXPECTED_FILES="
wheels-repo/simple/${DIST}/${DIST}-${VERSION}-py3-none-any.whl
work-dir/test-prebuilt.txt
"

pass=true
for f in $EXPECTED_FILES; do
  if [ ! -f "$OUTDIR/$f" ]; then
    echo "FAIL: Did not find $OUTDIR/$f" 1>&2
    pass=false
  fi
done

if $pass; then
  if ! grep -q "${DIST}==${VERSION}" $OUTDIR/work-dir/test-prebuilt.txt; then
    echo "FAIL: Did not find content in post-build hook output file" 1>&2
    pass=false
  fi
fi

$pass
