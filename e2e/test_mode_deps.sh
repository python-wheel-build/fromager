#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test --test-mode with a secondary dependency that fails to resolve
# stevedore depends on pbr; we constrain pbr to a non-existent version
# See: https://github.com/python-wheel-build/fromager/issues/895

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"
pass=true

DIST="stevedore"
VER="5.2.0"

# Constrain pbr to a version that doesn't exist
echo "pbr==99999.0.0" > "$OUTDIR/constraints.txt"

set +e
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --constraints-file="$OUTDIR/constraints.txt" \
  bootstrap --test-mode "${DIST}==${VER}"
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
  if ! jq -e '.failures[] | select(.package == "pbr")' "$failures_file" >/dev/null 2>&1; then
    echo "FAIL: pbr not found in failures" 1>&2
    pass=false
  fi

  failure_type=$(jq -r '[.failures[] | select(.package == "pbr")][0].failure_type' "$failures_file")
  if [ "$failure_type" != "resolution" ]; then
    echo "FAIL: expected failure_type 'resolution' for pbr, got '$failure_type'" 1>&2
    pass=false
  fi
fi

# stevedore should have resolved successfully
if ! grep -q "stevedore.*resolves to" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: stevedore did not resolve" 1>&2
  pass=false
fi

$pass
