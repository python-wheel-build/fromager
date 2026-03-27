#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests that --pypi-min-age applies to transitive dependencies, forcing both
# stevedore and its dependency pbr to fall back to older versions.
#
# Release timeline (all times UTC):
#
#   stevedore 5.1.0   2023-05-15  (the expected fallback for stevedore)
#   pbr 6.0.0         2023-11-07  (blocked by cooldown — the anchor date)
#   stevedore 5.2.0   2024-02-22  (blocked by cooldown)
#   pbr 6.1.0         2024-08-27  (blocked by cooldown)
#   stevedore 5.3.0+  2024-08-22+ (all blocked by cooldown)
#   pbr 7.x           2025-08-13+ (all blocked by cooldown)
#
#   pbr 5.11.1        2023-01-11  (the expected fallback for pbr)
#
# We compute --pypi-min-age dynamically as the age of pbr 6.0.0 in days plus
# a 1-day buffer.  This places the cutoff just past pbr 6.0.0's release,
# which also falls past stevedore 5.2.0 (released ~107 days after pbr 6.0.0).
#
# The margin between the cutoff and stevedore 5.1.0 is fixed at ~175 days
# (2023-11-07 minus 2023-05-15, less the 1-day buffer), so stevedore 5.1.0
# always clears the cooldown window regardless of when the test runs.
#
# The margin between the cutoff and pbr 5.11.1 is fixed at ~304 days
# (2023-11-07 minus 2023-01-11, less the 1-day buffer), so pbr 5.11.1
# similarly always clears the window.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Compute min-age: days since pbr 6.0.0 was published, plus a buffer.
# pbr 6.0.0 was released 2023-11-07; adding 1 day ensures it is always
# just inside the cooldown window and forces the resolver to pbr 5.11.1.
# Because stevedore 5.2.0 (2024-02-22) was released ~107 days after pbr
# 6.0.0, it is also blocked, and the resolver falls back to stevedore 5.1.0.
MIN_AGE=$(python3 -c "
from datetime import date
age = (date.today() - date(2023, 11, 7)).days
print(age + 1)
")

fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --pypi-min-age="$MIN_AGE" \
  bootstrap 'stevedore'

find "$OUTDIR/wheels-repo/" -name '*.whl'

pass=true

# stevedore 5.2.0+ are all blocked; the resolver must fall back to 5.1.0.
if ! grep -q "new toplevel dependency stevedore resolves to 5.1.0" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: expected stevedore to resolve to 5.1.0 but it did not" 1>&2
  pass=false
fi

# pbr 6.0.0+ are all blocked; the resolver must fall back to 5.11.1.
# pbr is first resolved as a build-backend dependency so we match any dep type.
if ! grep -q "dependency pbr.*resolves to 5.11.1" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: expected pbr to resolve to 5.11.1 but it did not" 1>&2
  pass=false
fi

# Confirm the expected wheels were actually produced.
if ! find "$OUTDIR/wheels-repo/downloads/" -name 'stevedore-5.1.0*.whl' | grep -q .; then
  echo "FAIL: stevedore-5.1.0 wheel not found in wheels-repo" 1>&2
  pass=false
fi

if ! find "$OUTDIR/wheels-repo/downloads/" -name 'pbr-5.11.1*.whl' | grep -q .; then
  echo "FAIL: pbr-5.11.1 wheel not found in wheels-repo" 1>&2
  pass=false
fi

$pass
