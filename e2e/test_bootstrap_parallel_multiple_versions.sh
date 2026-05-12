#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test bootstrap-parallel with --multiple-versions flag.
# Bootstraps flit-core 3.0.0 through 3.12.0 inclusive (many versions) with
# only 5 parallel workers to verify that batches larger than the worker pool
# are handled correctly.
#
# Note: flit-core <3.10.0 uses ast.Str which was removed in Python 3.14 and
# will fail during GET_BUILD_DEPS; those failures are expected and handled
# gracefully by the bootstrapper.  The test only asserts that the versions
# that *can* build (>=3.10.0) are present in the output.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Constrain flit-core (its own build backend) to the same range so the
# resolver never pulls in a version outside 3.0.0–3.12.0 as a build dep.
constraints_file=$(mktemp)
trap 'rm -f "$constraints_file"; on_exit' EXIT
cat > "$constraints_file" <<EOF
flit-core>=3.0.0,<=3.12.0
setuptools==82.0.1
poetry-core==2.4.0
tomli==2.4.1
toml==0.10.2
EOF

fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --constraints-file="$constraints_file" \
  bootstrap-parallel \
  --multiple-versions \
  --max-workers 5 \
  'flit-core>=3.0.0,<=3.12.0'

echo "Checking for flit-core wheels..."
find "$OUTDIR/wheels-repo/downloads/" -name 'flit_core-*.whl' | sort

# Verify that a representative sample of versions that can build on this
# Python (>=3.10.0, which dropped ast.Str) were bootstrapped.
# flit-core 3.0.0 through 3.12.0 includes many releases; 3.10.0–3.12.0
# are the ones compatible with Python 3.14+.
EXPECTED_VERSIONS="3.10.0 3.11.0 3.12.0"
MISSING_VERSIONS=""

for version in $EXPECTED_VERSIONS; do
  if find "$OUTDIR/wheels-repo/downloads/" -name "flit_core-${version}-*.whl" | grep -q .; then
    echo "found wheel for flit-core $version"
  else
    echo "missing wheel for flit-core $version" 1>&2
    MISSING_VERSIONS="$MISSING_VERSIONS $version"
  fi
done

if [ -n "$MISSING_VERSIONS" ]; then
  echo "" 1>&2
  echo "ERROR: Missing expected versions:$MISSING_VERSIONS" 1>&2
  echo "The --multiple-versions flag should have bootstrapped all matching versions" 1>&2
  echo "" 1>&2
  echo "Found flit-core wheels:" 1>&2
  find "$OUTDIR/wheels-repo/downloads/" -name 'flit_core-*.whl' 1>&2
  exit 1
fi

# Verify that the phases expected to parallelize each logged at least one
# "starting parallel batch" line, confirming the parallel code path ran.
#
# Note: "resolve" is intentionally excluded — with a single top-level
# requirement there is only one resolve item so that phase always runs serially.
PARALLEL_PHASES="start prepare-source get-build-deps build process-install-deps complete"
PHASES_WITHOUT_PARALLEL_BATCH=""

echo ""
echo "Checking that parallel phases ran at least one parallel batch..."
for phase in $PARALLEL_PHASES; do
  if grep -q "starting parallel batch: phase=${phase} " "$OUTDIR/bootstrap.log" 2>/dev/null; then
    echo "phase=${phase}: OK (parallel batch confirmed)"
  else
    echo "phase=${phase}: MISSING parallel batch" 1>&2
    PHASES_WITHOUT_PARALLEL_BATCH="${PHASES_WITHOUT_PARALLEL_BATCH} ${phase}"
  fi
done

if [ -n "$PHASES_WITHOUT_PARALLEL_BATCH" ]; then
  echo "" 1>&2
  echo "ERROR: these phases never ran a parallel batch:${PHASES_WITHOUT_PARALLEL_BATCH}" 1>&2
  exit 1
fi

echo "OK: all parallel phases ran at least one parallel batch"
echo ""
echo "SUCCESS: All sampled flit-core versions (3.10.0–3.12.0) were bootstrapped (from 3.0.0–3.12.0 range with 5 workers)"
