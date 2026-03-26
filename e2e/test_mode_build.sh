#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test --test-mode with a package that fails to build (no prebuilt fallback)
# Uses a local fixture that fails during wheel build; since it's not on PyPI,
# prebuilt fallback also fails and the failure is recorded.
# See: https://github.com/python-wheel-build/fromager/issues/895

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"
pass=true

DIST="test_build_failure"
FIXTURE_DIR="$SCRIPTDIR/test_build_failure"

# Initialize the fixture as a git repo (files are committed without .git)
created_git=false
if [ ! -d "$FIXTURE_DIR/.git" ]; then
  created_git=true
  (cd "$FIXTURE_DIR" && \
   git init -q && \
   git config user.email "test@example.com" && \
   git config user.name "Test User" && \
   git add -A && \
   git commit -q -m "init")
fi

# Clean up .git on exit if we created it
trap '[ "$created_git" = true ] && rm -rf "$FIXTURE_DIR/.git"' EXIT

echo "$DIST @ git+file://${FIXTURE_DIR}" > "$OUTDIR/requirements.txt"

set +e
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap --test-mode -r "$OUTDIR/requirements.txt"
exit_code=$?
set -e

if [ "$exit_code" -ne 1 ]; then
  echo "FAIL: expected exit code 1, got $exit_code" 1>&2
  pass=false
fi

failures_file=$(find "$OUTDIR/work-dir" -name "test-mode-failures-*.json" 2>/dev/null | head -1)

if [ -z "$failures_file" ]; then
  echo "FAIL: no test-mode-failures JSON file found" 1>&2
  pass=false
else
  if ! jq -e ".failures[] | select(.package == \"$DIST\")" "$failures_file" >/dev/null 2>&1; then
    echo "FAIL: $DIST not found in failures" 1>&2
    pass=false
  fi

  # Must be 'bootstrap' failure (actual build failure, not resolution)
  failure_type=$(jq -r "[.failures[] | select(.package == \"$DIST\")][0].failure_type" "$failures_file")
  if [ "$failure_type" != "bootstrap" ]; then
    echo "FAIL: expected failure_type 'bootstrap', got '$failure_type'" 1>&2
    pass=false
  fi
fi

if ! grep -q "test mode enabled" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: 'test mode enabled' not in log" 1>&2
  pass=false
fi

$pass
