#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests full bootstrap and installation of a complex package, without
# worrying about isolating the tools from upstream sources or
# restricting network access during the build. This allows us to test
# the overall logic of the build tools separately from the isolated
# build pipelines.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# passing settings to bootstrap but should have 0 effect on it
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  bootstrap 'stevedore==5.2.0' 'stevedore==4.0.0' || true

pass=true

# Check for log message that the override is loaded
if ! grep -q "Could not produce a pip compatible constraints file" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: did not throw an error when generating an incorrect constraints file" 1>&2
  pass=false
fi

$pass

if [ ! -f "$OUTDIR/work-dir/constraints.txt" ]; then
  echo "Did not find $OUTDIR/work-dir/constraints.txt" 1>&2
  pass=false
fi

$pass

EXPECTED_LINES="
pbr==6.1.0
# ERROR
stevedore==4.0.0
stevedore==5.2.0
"

for pattern in $EXPECTED_LINES; do
  if ! grep -q "${pattern}" "$OUTDIR/work-dir/constraints.txt"; then
    echo "Did not find $pattern in constraints file" 1>&2
    pass=false
  fi
done

$pass