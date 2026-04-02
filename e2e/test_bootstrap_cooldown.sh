#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests that --min-release-age rejects versions published within the cooldown
# window and falls back to an older stevedore version.  Verifies both the
# CLI flag (--min-release-age) and the equivalent environment variable
# (FROMAGER_MIN_RELEASE_AGE) produce identical behaviour.
#
# Release timeline (all times UTC):
#
#   stevedore 5.1.0   2023-05-15
#   stevedore 5.2.0   2024-02-22
#   stevedore 5.3.0   2024-08-22  (the expected fallback)
#   stevedore 5.4.0   2024-11-20  (blocked by cooldown)
#   stevedore 5.5.0+  future      (all blocked by cooldown)
#
# We compute --min-release-age dynamically as the age of stevedore 5.4.0 in
# days plus a 1-day buffer, ensuring stevedore 5.4.0 is always just inside the
# cooldown window while stevedore 5.3.0 (released ~90 days earlier) always
# clears it.
#
# Anchoring to 5.4.0 (released 2024-11-20) also ensures the build toolchain
# can use flit_core 3.10.0 (released 2024-10-31), which is required for
# Python 3.14 compatibility.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Compute min-age: days since stevedore 5.4.0 was published, plus a buffer.
# stevedore 5.4.0 was released 2024-11-20; adding 1 day ensures it is
# always just inside the cooldown window regardless of when the test runs.
MIN_AGE=$(python3 -c "
from datetime import date
age = (date.today() - date(2024, 11, 20)).days
print(age + 1)
")

# --- Pass 1: enforce cooldown via CLI flag ---

fromager \
  --log-file="$OUTDIR/bootstrap-flag.log" \
  --error-log-file="$OUTDIR/fromager-errors-flag.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --min-release-age="$MIN_AGE" \
  bootstrap 'stevedore'

pass=true

# stevedore 5.4.0 is blocked; the resolver must fall back to 5.3.0.
if ! grep -q "new toplevel dependency stevedore resolves to 5.3.0" "$OUTDIR/bootstrap-flag.log"; then
  echo "FAIL (flag): expected stevedore to resolve to 5.3.0 but it did not" 1>&2
  pass=false
fi

if ! find "$OUTDIR/wheels-repo/downloads/" -name 'stevedore-5.3.0*.whl' | grep -q .; then
  echo "FAIL (flag): stevedore-5.3.0 wheel not found in wheels-repo" 1>&2
  pass=false
fi

# --- Pass 2: enforce the same cooldown via environment variable (FROMAGER_MIN_RELEASE_AGE) ---

# Wipe output so the second run starts clean.
rm -rf "$OUTDIR/sdists-repo" "$OUTDIR/wheels-repo" "$OUTDIR/work-dir"

FROMAGER_MIN_RELEASE_AGE="$MIN_AGE" fromager \
  --log-file="$OUTDIR/bootstrap-envvar.log" \
  --error-log-file="$OUTDIR/fromager-errors-envvar.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  bootstrap 'stevedore'

if ! grep -q "new toplevel dependency stevedore resolves to 5.3.0" "$OUTDIR/bootstrap-envvar.log"; then
  echo "FAIL (envvar): expected stevedore to resolve to 5.3.0 but it did not" 1>&2
  pass=false
fi

if ! find "$OUTDIR/wheels-repo/downloads/" -name 'stevedore-5.3.0*.whl' | grep -q .; then
  echo "FAIL (envvar): stevedore-5.3.0 wheel not found in wheels-repo" 1>&2
  pass=false
fi

$pass
