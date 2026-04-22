#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests that resolver_dist.min_release_age = 0 in package settings bypasses
# the global --min-release-age flag for a specific package.
#
# Release timeline:
#
#   stevedore 5.3.0   2024-08-22  (passes the global cooldown — control)
#   stevedore 5.4.0   2024-11-20  (blocked by global cooldown — our target)
#
# The global cooldown is anchored to stevedore 5.4.0's release date so that
# 5.4.0 is just inside the cooldown window.  Without the per-package override,
# bootstrapping 'stevedore==5.4.0' would fail.  With min_release_age: 0 in the
# stevedore package settings, the cooldown is disabled for stevedore and the
# bootstrap must succeed.
#
# stevedore 5.4.0 is pinned explicitly so that only its build dependency
# (pbr>=2.0.0, satisfied by pbr 6.1.0 released 2024-08-27) is needed, and
# that version pre-dates the global cooldown cutoff.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Use the same anchor as test_bootstrap_cooldown.sh: cooldown would block
# stevedore 5.4.0 and force a fallback to 5.3.0.
MIN_AGE=$(python3 -c "
from datetime import date
age = (date.today() - date(2024, 11, 20)).days
print(age + 1)
")

fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/cooldown_override_settings" \
  --min-release-age="$MIN_AGE" \
  bootstrap 'stevedore==5.4.0'

pass=true

# The per-package override (min_release_age: 0) must have allowed 5.4.0 through.
if ! grep -q "new toplevel dependency stevedore.*resolves to 5.4.0" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: stevedore did not resolve to 5.4.0 — per-package cooldown override was not applied" 1>&2
  pass=false
fi

if ! find "$OUTDIR/wheels-repo/downloads/" -name 'stevedore-5.4.0*.whl' | grep -q .; then
  echo "FAIL: stevedore-5.4.0 wheel not found — expected cooldown override to allow it" 1>&2
  pass=false
fi

$pass
