#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test --test-mode: secondary dependency resolution failure
#
# Verifies that when a top-level package resolves but one of its dependencies
# cannot be resolved, test-mode records the failure and continues processing.
#
# See: https://github.com/python-wheel-build/fromager/issues/895

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Use stevedore which depends on pbr
# Constrain pbr to a version that doesn't exist to trigger secondary dep failure
TOPLEVEL_PKG="stevedore==5.2.0"
NONEXISTENT_VERSION="99999.0.0"

# Create a constraints file that forces pbr to a non-existent version
CONSTRAINTS_FILE="$OUTDIR/test-constraints.txt"
echo "pbr==${NONEXISTENT_VERSION}" > "$CONSTRAINTS_FILE"

# Run bootstrap in test mode
# The top-level stevedore should resolve, but pbr should fail
set +e
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --constraints-file="$CONSTRAINTS_FILE" \
  bootstrap --test-mode "${TOPLEVEL_PKG}"
EXIT_CODE=$?
set -e

pass=true

# Check 1: Exit code should be 1 (indicating failures in test mode)
if [ "$EXIT_CODE" -ne 1 ]; then
  echo "FAIL: Expected exit code 1, got $EXIT_CODE" 1>&2
  pass=false
fi

# Check 2: The test-mode-failures JSON file should exist
FAILURES_FILE=$(find "$OUTDIR/work-dir" -name "test-mode-failures-*.json" 2>/dev/null | head -1)
if [ -z "$FAILURES_FILE" ] || [ ! -f "$FAILURES_FILE" ]; then
  echo "FAIL: test-mode-failures-*.json file not found in $OUTDIR/work-dir" 1>&2
  ls -la "$OUTDIR/work-dir" 1>&2
  pass=false
else
  echo "Found failures file: $FAILURES_FILE"

  # Check 3: JSON file should contain at least one failure
  FAILURE_COUNT=$(jq '.failures | length' "$FAILURES_FILE")
  if [ "$FAILURE_COUNT" -lt 1 ]; then
    echo "FAIL: Expected at least 1 failure in JSON, got $FAILURE_COUNT" 1>&2
    jq '.' "$FAILURES_FILE" 1>&2
    pass=false
  fi

  # Check 4: pbr should be in the failed packages (secondary dependency)
  if ! jq -e '.failures[] | select(.package == "pbr")' "$FAILURES_FILE" > /dev/null 2>&1; then
    echo "FAIL: Expected 'pbr' to be in failed packages" 1>&2
    jq '.' "$FAILURES_FILE" 1>&2
    pass=false
  fi

  # Check 5: All pbr failures should be "resolution" type
  # Use first match since pbr may fail multiple times (as build dep of multiple packages)
  PBR_FAILURE_TYPE=$(jq -r '[.failures[] | select(.package == "pbr")][0].failure_type' "$FAILURES_FILE")
  if [ "$PBR_FAILURE_TYPE" != "resolution" ]; then
    echo "FAIL: Expected failure_type 'resolution' for pbr, got '$PBR_FAILURE_TYPE'" 1>&2
    jq '.' "$FAILURES_FILE" 1>&2
    pass=false
  fi
fi

# Check 6: Log should contain test mode messages
if ! grep -q "test mode enabled" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: Log should contain 'test mode enabled' message" 1>&2
  pass=false
fi

# Check 7: stevedore should have been resolved (top-level success)
if ! grep -q "stevedore.*resolves to" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: stevedore should have been resolved" 1>&2
  pass=false
fi

$pass
