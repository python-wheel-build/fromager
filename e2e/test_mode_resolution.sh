#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test --test-mode: top-level resolution failure
#
# Verifies that when a top-level package cannot be resolved (doesn't exist),
# test-mode records the failure in JSON and exits non-zero instead of crashing.
#
# See: https://github.com/python-wheel-build/fromager/issues/895

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Use a package name that definitely does not exist on PyPI
# This will trigger a resolution failure
NONEXISTENT_PKG="nonexistent-package-xyz-12345-does-not-exist"

# Run bootstrap in test mode with the non-existent package
# We expect this to exit with code 1 (failures recorded)
set +e
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap --test-mode "${NONEXISTENT_PKG}==1.0.0"
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

  # Check 3: JSON file should contain failures array with at least one entry
  FAILURE_COUNT=$(jq '.failures | length' "$FAILURES_FILE")
  if [ "$FAILURE_COUNT" -lt 1 ]; then
    echo "FAIL: Expected at least 1 failure in JSON, got $FAILURE_COUNT" 1>&2
    jq '.' "$FAILURES_FILE" 1>&2
    pass=false
  fi

  # Check 4: The failure should be for our non-existent package
  FAILED_PKG=$(jq -r '.failures[0].package' "$FAILURES_FILE")
  if [ "$FAILED_PKG" != "$NONEXISTENT_PKG" ]; then
    echo "FAIL: Expected failed package '$NONEXISTENT_PKG', got '$FAILED_PKG'" 1>&2
    jq '.' "$FAILURES_FILE" 1>&2
    pass=false
  fi

  # Check 5: The failure_type should be "resolution" (package doesn't exist)
  FAILURE_TYPE=$(jq -r '.failures[0].failure_type' "$FAILURES_FILE")
  if [ "$FAILURE_TYPE" != "resolution" ]; then
    echo "FAIL: Expected failure_type 'resolution', got '$FAILURE_TYPE'" 1>&2
    jq '.' "$FAILURES_FILE" 1>&2
    pass=false
  fi

  # Check 6: The failure should have an exception_type
  EXCEPTION_TYPE=$(jq -r '.failures[0].exception_type' "$FAILURES_FILE")
  if [ -z "$EXCEPTION_TYPE" ] || [ "$EXCEPTION_TYPE" = "null" ]; then
    echo "FAIL: Expected non-empty exception_type" 1>&2
    jq '.' "$FAILURES_FILE" 1>&2
    pass=false
  fi
fi

# Check 7: Log should contain test mode messages
if ! grep -q "test mode enabled" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: Log should contain 'test mode enabled' message" 1>&2
  pass=false
fi

if ! grep -q "test mode:.*failed" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: Log should contain test mode failure message" 1>&2
  pass=false
fi

$pass
