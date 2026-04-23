#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test bootstrap with --multiple-versions flag
# Tests that multiple matching versions are bootstrapped

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Create constraints file with generous ranges to test multiple versions
# of build dependencies (not just top-level packages)
constraints_file=$(mktemp)
trap "rm -f $constraints_file" EXIT
cat > "$constraints_file" <<EOF
# Allow a range of flit-core versions to verify multiple-versions works for dependencies
flit-core>=3.9,<3.12
EOF

# Compute --max-release-age dynamically: days since tomli 2.0.0 was uploaded
# to PyPI (2021-12-13) plus a buffer, so the oldest version is always included.
MAX_AGE=$(python3 -c "
from datetime import date
age = (date.today() - date(2021, 12, 13)).days
print(age + 30)
")

# Use tomli with a version range that matches exactly 3 versions (2.0.0, 2.0.1, 2.0.2)
# tomli has no runtime dependencies, making it fast to bootstrap
# It uses flit-core as build backend, and we allow multiple flit-core versions
# to test that --multiple-versions works for the entire dependency chain
# Using <=2.0.2 instead of <2.1 to be deterministic (tomli 2.1.0 exists)
# Note: constraints file generation is automatically disabled with --multiple-versions
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --constraints-file="$constraints_file" \
  bootstrap \
  --multiple-versions \
  --max-release-age="$MAX_AGE" \
  'tomli>=2.0,<=2.0.2'

# Check that wheels were built
echo "Checking for wheels..."
find "$OUTDIR/wheels-repo/downloads/" -name 'tomli-*.whl' | sort

# Verify that all expected versions were bootstrapped
# Note: We don't check the exact count to avoid test fragility if extra versions appear
EXPECTED_VERSIONS="2.0.0 2.0.1 2.0.2"
MISSING_VERSIONS=""

for version in $EXPECTED_VERSIONS; do
  if find "$OUTDIR/wheels-repo/downloads/" -name "tomli-$version-*.whl" | grep -q .; then
    echo "✓ Found wheel for tomli $version"
  else
    echo "✗ Missing wheel for tomli $version"
    MISSING_VERSIONS="$MISSING_VERSIONS $version"
  fi
done

if [ -n "$MISSING_VERSIONS" ]; then
  echo ""
  echo "ERROR: Missing expected versions:$MISSING_VERSIONS"
  echo "The --multiple-versions flag should have bootstrapped all matching versions"
  echo ""
  echo "Found wheels:"
  find "$OUTDIR/wheels-repo/downloads/" -name 'tomli-*.whl'
  exit 1
fi

echo ""
echo "SUCCESS: All expected tomli versions (2.0.0, 2.0.1, 2.0.2) were bootstrapped"

# Verify that multiple versions of flit-core were built (dependency of tomli)
# This confirms that --multiple-versions works for the entire dependency chain
echo ""
echo "Checking for flit-core versions (build dependency)..."
FLIT_CORE_COUNT=$(find "$OUTDIR/wheels-repo/downloads/" -name 'flit_core-3.*.whl' | wc -l)
echo "Found $FLIT_CORE_COUNT flit-core 3.x wheel(s)"

if [ "$FLIT_CORE_COUNT" -lt 2 ]; then
  echo ""
  echo "ERROR: Expected at least 2 flit-core versions, found $FLIT_CORE_COUNT"
  echo "The --multiple-versions flag should bootstrap multiple versions of dependencies too"
  echo ""
  echo "Found flit-core wheels:"
  find "$OUTDIR/wheels-repo/downloads/" -name 'flit_core-*.whl'
  exit 1
fi

echo "✓ Multiple versions of flit-core were bootstrapped (confirms dependency chain handling)"
