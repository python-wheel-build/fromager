#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests that --min-release-age applies to transitive dependencies, forcing
# pbr (a transitive dependency of stevedore) to fall back to an older version.
#
# Release timeline (all times UTC):
#
#   pbr 6.1.1         2025-02-04  (the expected fallback for pbr)
#   stevedore 5.4.1   2025-02-20  (resolves normally — not blocked)
#   stevedore 5.5.0   2025-08-25  (blocked by cooldown)
#   pbr 7.0.0         2025-08-13  (blocked by cooldown — the anchor date)
#   pbr 7.0.1+        2025-08-21+ (all blocked by cooldown)
#
# We compute --min-release-age dynamically as the age of pbr 7.0.0 in days
# plus a 1-day buffer.  This places the cutoff just before 2025-08-13, which
# blocks all pbr 7.x releases while allowing pbr 6.1.1 (2025-02-04) and
# stevedore 5.4.1 (2025-02-20) to pass.
#
# The cutoff (2025-08-12) also falls after flit_core 3.10.0 (2024-10-31),
# ensuring the build toolchain is Python 3.14 compatible.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Compute min-age: days since pbr 7.0.0 was published, plus a buffer.
# pbr 7.0.0 was released 2025-08-13; adding 1 day ensures it is always
# just inside the cooldown window and forces the resolver to pbr 6.1.1.
MIN_AGE=$(python3 -c "
from datetime import date
age = (date.today() - date(2025, 8, 13)).days
print(age + 1)
")

fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --min-release-age="$MIN_AGE" \
  bootstrap 'stevedore'

find "$OUTDIR/wheels-repo/" -name '*.whl'

pass=true

# stevedore resolves normally (5.4.1 is before the cutoff).
if ! grep -q "new toplevel dependency stevedore resolves to 5.4.1" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: expected stevedore to resolve to 5.4.1 but it did not" 1>&2
  pass=false
fi

# pbr 7.0.0+ are all blocked; the resolver must fall back to 6.1.1.
# pbr is first resolved as a build-backend dependency so we match any dep type.
if ! grep -q "dependency pbr.*resolves to 6.1.1" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: expected pbr to resolve to 6.1.1 but it did not" 1>&2
  pass=false
fi

# Confirm the expected wheels were actually produced.
if ! find "$OUTDIR/wheels-repo/downloads/" -name 'stevedore-5.4.1*.whl' | grep -q .; then
  echo "FAIL: stevedore-5.4.1 wheel not found in wheels-repo" 1>&2
  pass=false
fi

if ! find "$OUTDIR/wheels-repo/downloads/" -name 'pbr-6.1.1*.whl' | grep -q .; then
  echo "FAIL: pbr-6.1.1 wheel not found in wheels-repo" 1>&2
  pass=false
fi

$pass
