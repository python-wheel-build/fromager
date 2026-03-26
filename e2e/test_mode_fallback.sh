#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test --test-mode with a build failure that falls back to prebuilt wheel
# Uses a broken patch to fail the source build, then falls back to PyPI wheel.
# See: https://github.com/python-wheel-build/fromager/issues/895

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"
pass=true

DIST="setuptools"
VER="75.8.0"

# Force source build (not prebuilt)
mkdir -p "$OUTDIR/settings"
cat > "$OUTDIR/settings/${DIST}.yaml" << EOF
variants:
  cpu:
    pre_built: false
EOF

# Create a patch that will fail (wrong content for setup.py)
mkdir -p "$OUTDIR/patches/${DIST}"
cat > "$OUTDIR/patches/${DIST}/break-build.patch" << 'EOF'
--- a/setup.py
+++ b/setup.py
@@ -1,3 +1,3 @@
-wrong content
-that does not match
-the actual file
+will not
+be applied
+ever
EOF

set +e
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$OUTDIR/settings" \
  --patches-dir="$OUTDIR/patches" \
  bootstrap --test-mode "${DIST}==${VER}"
exit_code=$?
set -e

# Exit code should be 0 (fallback succeeded)
if [ "$exit_code" -ne 0 ]; then
  echo "FAIL: expected exit code 0, got $exit_code" 1>&2
  pass=false
fi

# Patch should have been attempted
if ! grep -q "applying patch file.*break-build.patch" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: patch was not applied" 1>&2
  pass=false
fi

# Fallback should have succeeded
if ! grep -q "successfully used pre-built wheel" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: prebuilt fallback did not succeed" 1>&2
  pass=false
fi

# No failures should be recorded
failures_file=$(find "$OUTDIR/work-dir" -name "test-mode-failures-*.json" 2>/dev/null | head -1)
if [ -n "$failures_file" ]; then
  failure_count=$(jq '.failures | length' "$failures_file")
  if [ "$failure_count" -gt 0 ]; then
    echo "FAIL: expected 0 failures, got $failure_count" 1>&2
    pass=false
  fi
fi

$pass
