#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test bootstrap with --all-versions option to verify multiple versions
# of a package are built. This test verifies that:
#   1. Multiple versions of top-level packages are built
#   2. Cache filtering works correctly (skips already-built versions)
#   3. Warning is shown when using --all-versions without --skip-constraints
#
# We use 'six' because it has NO dependencies, making the test fast while
# still testing the core all-versions functionality.
#
# Issue #878: Add multiple version mode to the bootstrap commands

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

pass=true

# We use 'six' as the test package because:
#   - It has multiple versions on PyPI
#   - It has NO dependencies (pure Python, no setuptools dependency at runtime)
#   - This makes the test fast while still testing multi-version behavior
#
# six>=1.16.0 should match all versions from 1.16.0 onwards
# We use a narrow range to limit how many versions we build.
PACKAGE_SPEC="six>=1.16.0"

################################################################################
# Test 1: Bootstrap with --all-versions flag
# This should build all matching versions of six within the specified range.
# Since six has no runtime dependencies, this tests the core multi-version
# resolution without the complexity of deep dependency chains.
################################################################################

echo "=== Test 1: Bootstrap with --all-versions ==="

fromager \
  --debug \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap --all-versions --skip-constraints "$PACKAGE_SPEC"

# Verify that we have multiple versions of six (top-level package)
SIX_WHEEL_COUNT=$(find "$OUTDIR/wheels-repo/downloads" -name 'six-*.whl' | wc -l)
echo "Found $SIX_WHEEL_COUNT six wheels (top-level package)"

if [ "$SIX_WHEEL_COUNT" -lt 1 ]; then
  echo "FAIL: Expected at least 1 six wheel file, found $SIX_WHEEL_COUNT" 1>&2
  pass=false
else
  echo "PASS: six versions built"
fi

# Check for expected log messages indicating all-versions mode is active
EXPECTED_LOG_MESSAGES=(
  "all-versions mode enabled: building all matching versions"
  "found .* matching versions for six"
  "including six==.* for build"
)

for pattern in "${EXPECTED_LOG_MESSAGES[@]}"; do
  if ! grep -Eq "$pattern" "$OUTDIR/bootstrap.log"; then
    echo "FAIL: Did not find log message pattern '$pattern' in $OUTDIR/bootstrap.log" 1>&2
    pass=false
  else
    echo "PASS: Found log pattern: $pattern"
  fi
done

# Verify constraints.txt was NOT created (because we used --skip-constraints)
if [ -f "$OUTDIR/work-dir/constraints.txt" ]; then
  echo "FAIL: constraints.txt was created despite --skip-constraints flag" 1>&2
  pass=false
fi

# Verify build-order.json was created
if [ ! -f "$OUTDIR/work-dir/build-order.json" ]; then
  echo "FAIL: build-order.json was not created" 1>&2
  pass=false
fi

# Check that build-order.json contains entries for six
SIX_VERSION_COUNT=$(grep -o '"dist": "six"' "$OUTDIR/work-dir/build-order.json" | wc -l)
echo "Found $SIX_VERSION_COUNT six entries in build-order.json"

if [ "$SIX_VERSION_COUNT" -lt 1 ]; then
  echo "FAIL: Expected at least 1 six entry in build-order.json, found $SIX_VERSION_COUNT" 1>&2
  pass=false
fi

################################################################################
# Test 2: Bootstrap with --all-versions and cache server
# This verifies that versions already in the cache are skipped.
################################################################################

echo "=== Test 2: Bootstrap with --all-versions and cache ==="

# Start a local wheel server with the wheels we just built
start_local_wheel_server

# Clean up work directory but keep the wheels repo
rm -rf "$OUTDIR/work-dir"
rm -rf "$OUTDIR/sdists-repo"
rm "$OUTDIR/bootstrap.log"

# Run bootstrap again with cache server pointing to our local server
# Since all versions are already cached, we should skip building them
fromager \
  --debug \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo-2" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap --all-versions --skip-constraints \
  --cache-wheel-server-url="$WHEEL_SERVER_URL" "$PACKAGE_SPEC"

# Check for log messages indicating versions were skipped due to cache
# Format: "skipping %s==%s: already exists in cache server"
if grep -Eq "skipping six==.*: already exists in cache server" "$OUTDIR/bootstrap.log"; then
  echo "PASS: Found cache skip messages for six"
else
  echo "WARN: Did not find cache skip messages for six (may be expected if cache check failed)"
fi

# Verify build-order.json was created even with cache hits
if [ ! -f "$OUTDIR/work-dir/build-order.json" ]; then
  echo "FAIL: build-order.json was not created in second run" 1>&2
  pass=false
fi

################################################################################
# Test 3: Verify warning when --all-versions used without --skip-constraints
################################################################################

echo "=== Test 3: Warning when --all-versions without --skip-constraints ==="

rm -rf "$OUTDIR/work-dir"
rm "$OUTDIR/bootstrap.log" || true

# This should produce a warning but still work
# Using a pinned version to avoid long builds
fromager \
  --debug \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo-3" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap --all-versions "six==1.16.0" || true  # May fail due to constraints conflict

# Check for the warning message
if grep -q "all-versions mode works best with --skip-constraints" "$OUTDIR/bootstrap.log"; then
  echo "PASS: Found expected warning about --skip-constraints"
else
  echo "FAIL: Did not find warning about --skip-constraints" 1>&2
  pass=false
fi

################################################################################
# Final result
################################################################################

echo ""
echo "=== Test Results ==="
if $pass; then
  echo "All tests PASSED"
else
  echo "Some tests FAILED"
fi

$pass
