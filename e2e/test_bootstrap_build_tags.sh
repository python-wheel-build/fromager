#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests full bootstrap with build tags

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# bootstrap stevedore with 1 change log
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  bootstrap 'stevedore==5.2.0'

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/stevedore-5.2.0-1*.whl
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

$pass

# bootstrap stevedore again with 1 change log. Should not result in a build
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-file="$SCRIPTDIR/bootstrap_settings.yaml" \
  bootstrap 'stevedore==5.2.0'

if ! grep -q "stevedore: have wheel version 5.2.0: $OUTDIR/wheels-repo/downloads/stevedore-5.2.0-1" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: Did not find log message have wheel version in $OUTDIR/bootstrap.log" 1>&2
  pass=false
fi

$pass

# bootstrap stevedore with 2 changelog. should result in a build instead of being skipped
fromager \
  --log-file="$OUTDIR/bootstrap_build_tags.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings-2" \
  bootstrap 'stevedore==5.2.0'

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/stevedore-5.2.0-1*.whl
$OUTDIR/wheels-repo/downloads/stevedore-5.2.0-2*.whl
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

if ! grep -q "added extra metadata and build tag" "$OUTDIR/bootstrap_build_tags.log"; then
  echo "Did not find message indicating builds would be skipped" 1>&2
  pass=false
fi

$pass
