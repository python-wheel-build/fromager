#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test --test-mode with a non-existent package (top-level resolution failure)
# See: https://github.com/python-wheel-build/fromager/issues/895

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"
pass=true

DIST="nonexistent-package-xyz-12345-does-not-exist"

set +e
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap --test-mode "${DIST}==1.0.0"
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

  failure_type=$(jq -r '.failures[0].failure_type' "$failures_file")
  if [ "$failure_type" != "resolution" ]; then
    echo "FAIL: expected failure_type 'resolution', got '$failure_type'" 1>&2
    pass=false
  fi
fi

if ! grep -q "test mode enabled" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: 'test mode enabled' not in log" 1>&2
  pass=false
fi

$pass
