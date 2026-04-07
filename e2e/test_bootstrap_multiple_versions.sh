#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test bootstrap with --multiple-versions flag
# Tests that multiple matching versions are bootstrapped

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Create constraints file to pin build dependencies (keeps CI fast)
constraints_file=$(mktemp)
trap "rm -f $constraints_file" EXIT
cat > "$constraints_file" <<EOF
flit-core==3.11.0
EOF

# Use tomli with a version range that matches exactly 3 versions (2.0.0, 2.0.1, 2.0.2)
# tomli has no runtime dependencies, making it fast to bootstrap
# It uses flit-core as build backend (pinned above)
# Using <=2.0.2 instead of <2.1 to be deterministic (tomli 2.1.0 exists)
# Note: constraints file generation will fail (expected with multiple versions)
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --constraints-file="$constraints_file" \
  bootstrap \
  --multiple-versions \
  'tomli>=2.0,<=2.0.2' || true

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
