#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests that --min-release-age rejects pre-built wheel candidates published
# within the cooldown window and falls back to an older stevedore version.
# This exercises the resolve_all_prebuilt_wheels() code path in wheels.py,
# which is taken when a package is configured with pre_built: true.
#
# Release timeline (wheel upload times, UTC):
#
#   stevedore 5.3.0   2024-08-22  (the expected fallback)
#   stevedore 5.4.0   2024-11-20  (blocked by cooldown)
#   stevedore 5.5.0+  future      (all blocked by cooldown)
#
# We use the same MIN_AGE anchor as test_bootstrap_cooldown.sh: the age of
# stevedore 5.4.0 (released 2024-11-20) plus a 1-day buffer, ensuring 5.4.0
# is always just inside the cooldown window while 5.3.0 (released ~90 days
# earlier) always clears it.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

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
  --settings-dir="$SCRIPTDIR/cooldown_prebuilt_settings" \
  --min-release-age="$MIN_AGE" \
  bootstrap 'stevedore'

pass=true

# stevedore 5.4.0's wheel is blocked; the resolver must fall back to 5.3.0.
if ! grep -q "new toplevel dependency stevedore resolves to 5.3.0" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: expected stevedore to resolve to 5.3.0 but it did not" 1>&2
  pass=false
fi

# The wheel must have been downloaded as a pre-built (not built from source).
if ! grep -q "uses a pre-built wheel" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: stevedore was not downloaded as a pre-built wheel" 1>&2
  pass=false
fi

# Wheel file must exist in the prebuilt directory.
if ! find "$OUTDIR/wheels-repo/prebuilt/" -name 'stevedore-5.3.0*.whl' | grep -q .; then
  echo "FAIL: stevedore-5.3.0 wheel not found in wheels-repo/prebuilt" 1>&2
  pass=false
fi

# No stevedore sdist should have been downloaded — it is pre_built only.
if find "$OUTDIR/sdists-repo/" \( -name 'stevedore*.tar.gz' -o -name 'stevedore*.zip' \) 2>/dev/null | grep -q .; then
  echo "FAIL: stevedore sdist found in sdists-repo — should be pre-built only" 1>&2
  pass=false
fi

$pass
