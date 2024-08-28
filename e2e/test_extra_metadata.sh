#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test whether extra metadata was added in the wheels or not

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/build_settings" \
  bootstrap 'stevedore==5.2.0'

find "$OUTDIR/wheels-repo/" -name '*.whl'
find "$OUTDIR/sdists-repo/" -name '*.tar.gz'
ls "$OUTDIR"/work-dir/*/build.log || true

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/setuptools-*.whl
$OUTDIR/wheels-repo/downloads/pbr-*.whl
$OUTDIR/wheels-repo/downloads/stevedore-*.whl
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

$pass

wheel unpack $OUTDIR/wheels-repo/downloads/stevedore-5.2.0-0-py3-none-any.whl -d $OUTDIR

EXPECTED_FILES="
$OUTDIR/stevedore-5.2.0/stevedore-5.2.0.dist-info/fromager-build-settings
$OUTDIR/stevedore-5.2.0/stevedore-5.2.0.dist-info/fromager-build-backend-requirements.txt
$OUTDIR/stevedore-5.2.0/stevedore-5.2.0.dist-info/fromager-build-system-requirements.txt
$OUTDIR/stevedore-5.2.0/stevedore-5.2.0.dist-info/fromager-build-sdist-requirements.txt
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

$pass

for file in $EXPECTED_FILES; do
  cat $file
done
