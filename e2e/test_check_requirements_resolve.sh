#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# e2e test for the check-requirements-resolve command

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

pass=true

# Valid constraints.txt and requirements.txt should all resolve
if ! fromager \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  check-requirements-resolve \
    "$SCRIPTDIR/validate_inputs/requirements.txt"; then
  echo "FAIL: valid requirements should resolve" 1>&2
  pass=false
fi

# No arguments error
if fromager \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  check-requirements-resolve; then
  echo "FAIL: missing input files should be recognized" 1>&2
  pass=false
fi

# Bad requirement syntax error
if fromager \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  check-requirements-resolve \
    "$SCRIPTDIR/validate_inputs/invalid-requirements.txt"; then
  echo "FAIL: invalid requirement syntax should error" 1>&2
  pass=false
fi

# Non-existent package resolution failure
if fromager \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  check-requirements-resolve \
    "$SCRIPTDIR/validate_inputs/non-resolving-requirements.txt"; then
  echo "FAIL: resolution of a non-existent package should fail" 1>&2
  pass=false
fi

$pass
