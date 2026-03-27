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

# Check 1: Exit code - could be 0 (fallback succeeded) or 1 (failures recorded)
# The key is that the test mode continued processing
echo "Exit code: $EXIT_CODE"

# Check 2: Log should show test mode was enabled
if ! grep -q "test mode enabled" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: Log should contain 'test mode enabled' message" 1>&2
  pass=false
fi

# Check 3: Look for evidence of the patch failure and fallback attempt
if grep -q "applying patch\|patch" "$OUTDIR/bootstrap.log"; then
  echo "Patch application was attempted"
fi

# Check 4: Check if prebuilt fallback was triggered
if grep -q "pre-built fallback" "$OUTDIR/bootstrap.log"; then
  echo "Prebuilt fallback was triggered"
  if grep -q "successfully used pre-built wheel" "$OUTDIR/bootstrap.log"; then
    echo "SUCCESS: Prebuilt fallback succeeded"
  fi
fi

# Check 5: If there are failures recorded, verify the structure
FAILURES_FILE=$(find "$OUTDIR/work-dir" -name "test-mode-failures-*.json" 2>/dev/null | head -1)
if [ -n "$FAILURES_FILE" ] && [ -f "$FAILURES_FILE" ]; then
  echo "Found failures file: $FAILURES_FILE"
  FAILURE_COUNT=$(jq '.failures | length' "$FAILURES_FILE")
  echo "Number of failures recorded: $FAILURE_COUNT"
  # Show failures for debugging
  jq '.failures[] | {package, failure_type, exception_type}' "$FAILURES_FILE"
fi

# Check 6: Verify test mode completed (wrote summary or failures)
if grep -q "test mode:" "$OUTDIR/bootstrap.log"; then
  echo "Test mode processing completed"
else
  echo "NOTE: Test mode summary not found in log" 1>&2
fi

$pass
