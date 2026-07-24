#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test that --multiple-versions continues when one package fails to resolve.
# A nonexistent package triggers a resolution failure; a real package (tomli)
# should still be bootstrapped successfully.
# See: https://github.com/python-wheel-build/fromager/issues/1195

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"
pass=true

# Compute --max-release-age dynamically so tomli 2.0.1 is always included.
MAX_AGE=$(python3 -c "
from datetime import date
age = (date.today() - date(2021, 12, 13)).days
print(age + 30)
")

# Bootstrap two packages:
# - nonexistent-pkg-xyz-99999: guaranteed resolution failure
# - tomli==2.0.1: should resolve and build successfully
#
# The bootstrap must not crash on the nonexistent package.
set +e
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap \
  --multiple-versions \
  --max-release-age="$MAX_AGE" \
  'nonexistent-pkg-xyz-99999==1.0.0' 'tomli==2.0.1'
exit_code=$?
set -e

# The bootstrap should succeed (exit 0) despite the resolution failure
if [ "$exit_code" -ne 0 ]; then
  echo "FAIL: expected exit code 0, got $exit_code" 1>&2
  echo "multiple-versions mode should continue past resolution failures" 1>&2
  pass=false
fi

# Verify that tomli was built successfully
if find "$OUTDIR/wheels-repo/downloads/" -name 'tomli-2.0.1*.whl' | grep -q .; then
  echo "✓ tomli wheel was built despite nonexistent-pkg resolution failure"
else
  echo "FAIL: tomli wheel not found — bootstrap may have crashed early" 1>&2
  pass=false
fi

# Verify that the resolution failure for the nonexistent package was logged
if grep -q "nonexistent-pkg-xyz-99999.*failed to resolve" "$OUTDIR/bootstrap.log"; then
  echo "✓ Resolution failure was logged for nonexistent package"
else
  echo "FAIL: resolution failure message not found in log" 1>&2
  pass=false
fi

# Verify the failed versions summary was logged
if grep -q "version(s) failed to bootstrap" "$OUTDIR/bootstrap.log"; then
  echo "✓ Failed versions summary was logged"
else
  echo "FAIL: failed versions summary not found in log" 1>&2
  pass=false
fi

$pass
