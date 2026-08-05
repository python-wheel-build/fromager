#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test that constrained (pinned) packages bypass max-release-age filtering.
# A package pinned in constraints should always be built regardless of its age,
# because a constraint pin is explicit user intent that takes precedence over
# the age filter heuristic.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# tomli 2.0.0 was uploaded to PyPI on 2021-12-13.
# We set --max-release-age to a value that EXCLUDES tomli 2.0.0
# but INCLUDES tomli 2.0.1 (2022-01-02) and 2.0.2 (2025-05-05).
# Then we pin tomli==2.0.0 in constraints — it must still be built.
MAX_AGE=$(python3 -c "
from datetime import date
# Age of tomli 2.0.1 (uploaded 2022-01-02) + 10 day buffer
# This ensures 2.0.1 is inside the window but 2.0.0 is outside
age = (date.today() - date(2022, 1, 2)).days + 10
print(age)
")

echo "Using --max-release-age=$MAX_AGE"

# Create constraints file pinning tomli to the OLD version
constraints_file=$(mktemp)
trap 'rm -f "$constraints_file"; on_exit' EXIT
cat > "$constraints_file" <<EOF
tomli==2.0.0
EOF

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

# Verify that the pinned old version was built despite being outside the age window
echo ""
echo "Checking that constrained (pinned) version was built..."
if find "$OUTDIR/wheels-repo/downloads/" -name "tomli-2.0.0-*.whl" | grep -q .; then
  echo "✓ Found wheel for tomli 2.0.0 (constrained — bypassed age filter)"
else
  echo "✗ Missing wheel for tomli 2.0.0"
  echo "ERROR: tomli 2.0.0 is pinned in constraints and should bypass age filtering"
  echo ""
  echo "Found wheels:"
  find "$OUTDIR/wheels-repo/downloads/" -name 'tomli-*.whl'
  exit 1
fi

# Verify the log confirms the constraint bypass
echo ""
echo "Checking log for constraint bypass..."
if grep -q "skipping age filter for pinned constraint" "$OUTDIR/bootstrap.log"; then
  echo "✓ Log confirms age filter was bypassed for pinned constraint"
else
  echo "✗ No constraint bypass message found in log"
  exit 1
fi

echo ""
echo "SUCCESS: Constrained package correctly bypassed age filtering"
