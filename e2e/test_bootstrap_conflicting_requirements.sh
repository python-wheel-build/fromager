#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests full bootstrap and installation of a complex package, without
# worrying about isolating the tools from upstream sources or
# restricting network access during the build. This allows us to test
# the overall logic of the build tools separately from the isolated
# build pipelines.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# expected pbr version
constraints_file=$(mktemp)
trap "rm -f $constraints_file" EXIT
echo "pbr==6.1.1" > "$constraints_file"

# passing settings to bootstrap but should have 0 effect on it
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  --constraints-file="$constraints_file" \
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

# With the corrected constraint resolution algorithm, only non-conflicting
# packages should be written to the constraints file. Conflicting packages
# (stevedore versions) should be excluded entirely.
EXPECTED_LINES="
pbr==6.1.1
"

SHOULD_NOT_BE_PRESENT="
stevedore==4.0.0
stevedore==5.2.0
ERROR
"

# Check that non-conflicting packages are present
for pattern in $EXPECTED_LINES; do
  if ! grep -q "${pattern}" "$OUTDIR/work-dir/constraints.txt"; then
    echo "Did not find $pattern in constraints file" 1>&2
    pass=false
  fi
done

# Check that conflicting packages are NOT present
for pattern in $SHOULD_NOT_BE_PRESENT; do
  if grep -q "${pattern}" "$OUTDIR/work-dir/constraints.txt"; then
    echo "Found $pattern in constraints file (should not be present)" 1>&2
    pass=false
  fi
done

$pass
