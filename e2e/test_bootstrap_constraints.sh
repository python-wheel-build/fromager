#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests full bootstrap and installation of a complex package, without
# worrying about isolating the tools from upstream sources or
# restricting network access during the build. This allows us to test
# the overall logic of the build tools separately from the isolated
# build pipelines.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

constraints_file=$(mktemp)
echo "stevedore==4.0.0" > "$constraints_file"

# passing settings to bootstrap but should have 0 effect on it
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  --constraints-file="$constraints_file" \
  bootstrap 'stevedore==5.2.0' || true

pass=true

# Check for log message that the override is loaded
if ! grep -q "ERROR: Unable to resolve requirement specifier stevedore==5.2.0 with constraint stevedore==4.0.0" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: did not throw expected error when constraint and requirement conflict" 1>&2
  pass=false
fi

$pass
