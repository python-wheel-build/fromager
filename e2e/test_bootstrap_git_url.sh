#!/bin/bash

# Test bootstrapping from a requirement with a git+https URL witout specifying a
# version tag.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

GIT_REPO_URL="https://github.com/python-wheel-build/stevedore-test-repo.git"

fromager \
  --debug \
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

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/setuptools-*.whl
$OUTDIR/wheels-repo/downloads/pbr-*.whl
$OUTDIR/wheels-repo/downloads/stevedore-*.whl

$OUTDIR/sdists-repo/downloads/setuptools-*.tar.gz
$OUTDIR/sdists-repo/downloads/pbr-*.tar.gz

$OUTDIR/sdists-repo/builds/stevedore-*.tar.gz
$OUTDIR/sdists-repo/builds/setuptools-*.tar.gz
$OUTDIR/sdists-repo/builds/pbr-*.tar.gz

$OUTDIR/work-dir/build-order.json
$OUTDIR/work-dir/constraints.txt

$OUTDIR/bootstrap.log
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
