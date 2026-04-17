#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test --test-mode: build failure with prebuilt fallback
#
# Verifies that when a source build fails but a prebuilt wheel is available,
# test-mode uses the prebuilt wheel as fallback and continues without failure.
# Uses a broken patch to trigger the build failure, then falls back to PyPI wheel.
#
# See: https://github.com/python-wheel-build/fromager/issues/895

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Use setuptools - it's on PyPI with prebuilt wheels
DIST="setuptools"
VERSION="75.8.0"

# Step 1: Configure settings to mark setuptools as NOT prebuilt
# This forces fromager to try building from source
SETTINGS_DIR="$OUTDIR/test-settings"
mkdir -p "$SETTINGS_DIR"
cat > "$SETTINGS_DIR/${DIST}.yaml" << EOF
variants:
  cpu:
    pre_built: false
EOF

# Step 2: Create a broken patches dir that will cause build to fail
# We create a patch targeting setup.py with wrong content - patch will fail
# without prompting for input (unlike targeting a non-existent file)
PATCHES_DIR="$OUTDIR/test-patches"
mkdir -p "$PATCHES_DIR/${DIST}"
cat > "$PATCHES_DIR/${DIST}/break-build.patch" << 'PATCHEOF'
--- a/setup.py
+++ b/setup.py
@@ -1,3 +1,3 @@
-this content does not match
-the actual setup.py file
-so patch will fail
+replaced content
+that will never
+be applied
PATCHEOF

# Step 3: Run bootstrap in test mode
# - Package will resolve from PyPI
# - Source preparation will fail (bad patch)
# - Prebuilt fallback should succeed (wheel on PyPI)
echo "Running test-mode bootstrap with broken patch..."
set +e
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SETTINGS_DIR" \
  --patches-dir="$PATCHES_DIR" \
  bootstrap --test-mode "${DIST}==${VERSION}"
EXIT_CODE=$?
set -e

pass=true

# Check 1: Exit code should be 0 (fallback succeeded, no failures recorded)
echo "Exit code: $EXIT_CODE"
if [ "$EXIT_CODE" -ne 0 ]; then
  echo "FAIL: Expected exit code 0 (fallback success), got $EXIT_CODE" 1>&2
  pass=false
fi

# Check 2: Log should show test mode was enabled
if ! grep -q "test mode enabled" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: Log should contain 'test mode enabled' message" 1>&2
  pass=false
fi

# Check 3: Patch application must be attempted
if ! grep -q "applying patch file.*break-build.patch" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: Expected patch 'break-build.patch' to be applied" 1>&2
  pass=false
else
  echo "Patch application was attempted"
fi

# Check 4: Prebuilt fallback MUST be triggered and succeed
if ! grep -q "pre-built fallback" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: Expected prebuilt fallback to be triggered" 1>&2
  pass=false
elif ! grep -q "successfully used pre-built wheel" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: Prebuilt fallback was triggered but did not succeed" 1>&2
  pass=false
else
  echo "SUCCESS: Prebuilt fallback triggered and succeeded"
fi

# Check 5: No failures should be recorded (fallback succeeded)
FAILURES_FILE=$(find "$OUTDIR/work-dir" -name "test-mode-failures-*.json" 2>/dev/null | head -1)
if [ -n "$FAILURES_FILE" ] && [ -f "$FAILURES_FILE" ]; then
  FAILURE_COUNT=$(jq '.failures | length' "$FAILURES_FILE")
  if [ "$FAILURE_COUNT" -gt 0 ]; then
    echo "FAIL: Expected no failures (fallback should succeed), got $FAILURE_COUNT" 1>&2
    jq '.failures[] | {package, failure_type, exception_type}' "$FAILURES_FILE" 1>&2
    pass=false
  fi
fi

# Check 6: Verify test mode completed
if grep -q "test mode:" "$OUTDIR/bootstrap.log"; then
  echo "Test mode processing completed"
else
  echo "NOTE: Test mode summary not found in log" 1>&2
fi

$pass
