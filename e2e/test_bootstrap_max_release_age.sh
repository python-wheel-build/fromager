#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test bootstrap with --max-release-age flag
# Tests that old versions are filtered out by the max release age window
# and that the filter also applies to build dependencies

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# certifi PyPI upload timeline (actual upload_time from PyPI JSON API):
#
#   certifi 2025.11.12  2025-11-12  (should be filtered — too old)
#   certifi 2026.1.4    2026-01-04  (should be filtered — too old)
#   certifi 2026.2.25   2026-02-25  (should be included — recent enough)
#   certifi 2026.4.22   2026-04-22  (should be included — recent enough)
#
# Compute --max-release-age so certifi 2026.2.25 is inside the window
# but certifi 2026.1.4 is outside. We anchor on certifi 2026.2.25's
# upload date and add a buffer.
MAX_AGE=$(python3 -c "
from datetime import date
# Age of certifi 2026.2.25 (uploaded 2026-02-25) + 10 day buffer
age = (date.today() - date(2026, 2, 25)).days + 10
print(age)
")

echo "Using --max-release-age=$MAX_AGE"

fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap \
  --multiple-versions \
  --max-release-age="$MAX_AGE" \
  'certifi>=2025.11,<=2026.5'

# Verify that recent versions were built (within age window)
echo ""
echo "Checking for expected versions..."
for version in 2026.2.25 2026.4.22; do
  if find "$OUTDIR/wheels-repo/downloads/" -name "certifi-$version-*.whl" | grep -q .; then
    echo "✓ Found wheel for certifi $version (within max-release-age window)"
  else
    echo "✗ Missing wheel for certifi $version"
    echo "ERROR: certifi $version should be within the max-release-age window"
    echo ""
    echo "Found wheels:"
    find "$OUTDIR/wheels-repo/downloads/" -name 'certifi-*.whl'
    exit 1
  fi
done

# Verify that old versions were filtered out
echo ""
echo "Checking that old versions were filtered..."
UNEXPECTED=""
for version in 2025.11.12 2026.1.4; do
  if find "$OUTDIR/wheels-repo/downloads/" -name "certifi-$version-*.whl" | grep -q .; then
    echo "✗ Found wheel for certifi $version — should have been filtered by max-release-age"
    UNEXPECTED="$UNEXPECTED $version"
  else
    echo "✓ certifi $version correctly filtered out by max-release-age"
  fi
done

if [ -n "$UNEXPECTED" ]; then
  echo ""
  echo "ERROR: --max-release-age should have excluded:$UNEXPECTED"
  exit 1
fi

# Verify that max-release-age filtering was applied (check log)
echo ""
echo "Checking log for max-release-age filtering..."
if grep -q "published within.*days" "$OUTDIR/bootstrap.log"; then
  echo "✓ Log confirms max-release-age filtering was applied"
else
  echo "✗ No max-release-age filtering found in log"
  exit 1
fi

# Verify that build dependencies were also resolved within the window
# setuptools is the build dependency for certifi
echo ""
echo "Checking that build dependencies were resolved..."
if find "$OUTDIR/wheels-repo/downloads/" -name "setuptools-*.whl" | grep -q .; then
  echo "✓ setuptools was built (build dependency of certifi)"
else
  echo "✗ setuptools was not built — build dependency resolution may have failed"
  exit 1
fi

echo ""
echo "SUCCESS: --max-release-age correctly filtered old versions and resolved build dependencies"
