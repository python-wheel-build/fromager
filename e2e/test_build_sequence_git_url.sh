#!/bin/bash

# Test bootstrapping from a requirement with a git+https URL witout specifying a
# version tag.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

GIT_REPO_URL="https://github.com/python-wheel-build/stevedore-test-repo.git"

fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  bootstrap "stevedore @ git+${GIT_REPO_URL}"

find "$OUTDIR/wheels-repo/" -name '*.whl'
find "$OUTDIR/sdists-repo/" -name '*.tar.gz'
ls "$OUTDIR"/work-dir/*/build.log || true

# Clean up the work directory so we can test build-sequence
mv "$OUTDIR/work-dir/build-order.json" "$OUTDIR/"
rm -rf "$OUTDIR/work-dir/wheels-repo"
rm -rf "$OUTDIR/work-dir/sdists-repo"

# Rebuild using the build-order file and build-sequence
log="$OUTDIR/build.log"
cat "$OUTDIR/build-order.json" | jq . | tee -a "$log"

fromager \
    --debug \
    --log-file "$log" \
    --work-dir "$OUTDIR/work-dir" \
    --sdists-repo "$OUTDIR/sdists-repo" \
    --wheels-repo "$OUTDIR/wheels-repo" \
    --settings-dir="$SCRIPTDIR/changelog_settings" \
    build-sequence --force "$OUTDIR/build-order.json"

find "$OUTDIR/wheels-repo/" -name '*.whl'
find "$OUTDIR/sdists-repo/" -name '*.tar.gz'
ls "$OUTDIR"/work-dir/*/build.log || true

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/setuptools-*.whl
$OUTDIR/wheels-repo/downloads/pbr-*.whl
$OUTDIR/wheels-repo/downloads/stevedore-*.whl

$OUTDIR/sdists-repo/downloads/setuptools-*.tar.gz
$OUTDIR/sdists-repo/downloads/pbr-*.tar.gz

$OUTDIR/sdists-repo/builds/stevedore-*.tar.gz
$OUTDIR/sdists-repo/builds/setuptools-*.tar.gz
$OUTDIR/sdists-repo/builds/pbr-*.tar.gz

$OUTDIR/bootstrap.log
$OUTDIR/build.log
$OUTDIR/fromager-errors.log

$OUTDIR/work-dir/pbr-*/build.log
$OUTDIR/work-dir/setuptools-*/build.log
$OUTDIR/work-dir/stevedore-*/build.log
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

$pass

twine check $OUTDIR/sdists-repo/builds/*.tar.gz
twine check $OUTDIR/wheels-repo/downloads/*.whl
