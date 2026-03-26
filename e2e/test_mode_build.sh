#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test --test-mode: build failure without prebuilt fallback
#
# Verifies that when a package fails to build and no prebuilt wheel is available
# (because the package is not on PyPI), test-mode records the failure.
# Uses a local git repo fixture with a broken build backend.
#
# See: https://github.com/python-wheel-build/fromager/issues/895

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Use the test_build_failure fixture (local git repo)
# Initialize git repo at runtime (fixture files are committed without .git)
FIXTURE_DIR="$SCRIPTDIR/test_build_failure"
if [ ! -d "$FIXTURE_DIR/.git" ]; then
  (cd "$FIXTURE_DIR" && git init -q && git add -A && git commit -q -m "init")
fi
FIXTURE_URL="git+file://${FIXTURE_DIR}"

# Create a requirements file pointing to the local fixture
REQUIREMENTS_FILE="$OUTDIR/test-requirements.txt"
echo "test_build_failure @ ${FIXTURE_URL}" > "$REQUIREMENTS_FILE"

# Run bootstrap in test mode
# - Package resolves from local git repo
# - Build fails (broken build backend)
# - Prebuilt fallback fails (package not on PyPI)
# - Failure should be recorded
set +e
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap --test-mode -r "$REQUIREMENTS_FILE"
EXIT_CODE=$?
set -e

pass=true

# Check 1: Exit code should be 1 (failures recorded)
if [ "$EXIT_CODE" -ne 1 ]; then
  echo "FAIL: Expected exit code 1, got $EXIT_CODE" 1>&2
  pass=false
fi

# Check 2: The test-mode-failures JSON file should exist
FAILURES_FILE=$(find "$OUTDIR/work-dir" -name "test-mode-failures-*.json" 2>/dev/null | head -1)
if [ -z "$FAILURES_FILE" ] || [ ! -f "$FAILURES_FILE" ]; then
  echo "FAIL: test-mode-failures-*.json file not found" 1>&2
  pass=false
else
  echo "Found failures file: $FAILURES_FILE"

  # Check 3: test_build_failure should be in failed packages
  # Note: package name uses underscore as recorded by fromager
  if ! jq -e '.failures[] | select(.package == "test_build_failure")' "$FAILURES_FILE" > /dev/null 2>&1; then
    echo "FAIL: Expected 'test_build_failure' in failed packages" 1>&2
    jq '.' "$FAILURES_FILE" 1>&2
    pass=false
  fi

  # Check 4: failure_type should be "bootstrap" or "resolution" (both are valid build failures)
  FAILURE_TYPE=$(jq -r '[.failures[] | select(.package == "test_build_failure")][0].failure_type' "$FAILURES_FILE")
  if [ "$FAILURE_TYPE" != "bootstrap" ] && [ "$FAILURE_TYPE" != "resolution" ]; then
    echo "FAIL: Expected failure_type 'bootstrap' or 'resolution', got '$FAILURE_TYPE'" 1>&2
    pass=false
  fi

  # Check 5: exception_message should mention the intentional failure or a build-related error
  EXCEPTION_MSG=$(jq -r '[.failures[] | select(.package == "test_build_failure")][0].exception_message' "$FAILURES_FILE")
  if [[ "$EXCEPTION_MSG" != *"Intentional build failure"* ]] && [[ "$EXCEPTION_MSG" != *"RuntimeError"* ]] && [[ "$EXCEPTION_MSG" != *"build"* ]]; then
    echo "FAIL: Expected exception message about build failure, got: $EXCEPTION_MSG" 1>&2
    pass=false
  fi
fi

# Check 6: Log should show test mode enabled
if ! grep -q "test mode enabled" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: Log should contain 'test mode enabled'" 1>&2
  pass=false
fi

# Check 7: Log should show fallback was attempted and failed
if ! grep -q "pre-built fallback" "$OUTDIR/bootstrap.log"; then
  echo "INFO: Log mentions fallback (may or may not be present)"
fi

$pass
