#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests constraints with prerelease and without prerelease

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

DIST="flit_core<2.0.1"

# building flit_core 2.0 is not possible because it requires pytoml. we just care about resolution anyways
fromager \
  --verbose \
  --log-file="$OUTDIR/bootstrap.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap $DIST || true

pass=true

# Check for log message that the override is loaded
if ! grep -q "flit_core: new toplevel dependency flit_core<2.0.1 resolves to 2.0" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: flit_core did not resolve to 2.0 $OUTDIR/bootstrap.log" 1>&2
  pass=false
fi

$pass

CONSTRAINTS_FILE="$OUTDIR/flit_core_constraints.txt"
echo "flit_core==2.0rc3" > $CONSTRAINTS_FILE

DEBUG_RESOLVER=true fromager \
  --verbose \
  --log-file="$OUTDIR/bootstrap.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --constraints-file="$CONSTRAINTS_FILE" \
  bootstrap $DIST || true


# Check for log message that the override is loaded
if ! grep -q "flit_core: new toplevel dependency flit_core<2.0.1 resolves to 2.0rc3" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: flit_core did not resolve to 2.0rc3 $OUTDIR/bootstrap.log" 1>&2
  pass=false
fi

$pass