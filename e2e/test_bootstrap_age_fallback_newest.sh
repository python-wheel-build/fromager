#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test that multi-version bootstrap with --max-release-age falls back to
# building only the newest version when ALL versions are outside the age window.
# Without this fallback, the bootstrap would fail entirely.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Use --max-release-age=1 so ALL tomli versions are outside the window.
# The newest matching version should still be built via the NEWEST fallback.
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap \
  --multiple-versions \
  --max-release-age=1 \
  'tomli>=2.0,<=2.0.2'

# Count how many tomli wheels were built
TOMLI_COUNT=$(find "$OUTDIR/wheels-repo/downloads/" -name "tomli-*.whl" | wc -l)
echo "Found $TOMLI_COUNT tomli wheel(s)"

# Exactly one version should be built (the newest fallback)
if [ "$TOMLI_COUNT" -eq 1 ]; then
  echo "✓ Exactly one tomli version was built (newest fallback)"
else
  echo "✗ Expected exactly 1 tomli version, found $TOMLI_COUNT"
  echo "The NEWEST fallback should build only the single newest version"
  echo ""
  echo "Found wheels:"
  find "$OUTDIR/wheels-repo/downloads/" -name 'tomli-*.whl'
  exit 1
fi

# The newest matching version (2.0.2) should be the one built
if find "$OUTDIR/wheels-repo/downloads/" -name "tomli-2.0.2-*.whl" | grep -q .; then
  echo "✓ Found wheel for tomli 2.0.2 (newest matching version)"
else
  echo "✗ Missing wheel for tomli 2.0.2 — expected the newest version"
  echo ""
  echo "Found wheels:"
  find "$OUTDIR/wheels-repo/downloads/" -name 'tomli-*.whl'
  exit 1
fi

# Verify the log confirms the fallback was triggered
echo ""
echo "Checking log for newest fallback..."
if grep -q "falling back to newest version" "$OUTDIR/bootstrap.log"; then
  echo "✓ Log confirms newest version fallback was triggered"
else
  echo "✗ No newest-version fallback message found in log"
  exit 1
fi

echo ""
echo "SUCCESS: Multi-version age fallback correctly built only the newest version"
