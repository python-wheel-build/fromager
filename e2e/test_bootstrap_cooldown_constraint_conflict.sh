#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests that --pypi-min-age causes resolution to fail with a clear error when
# a constraint pins a dependency to a version that falls within the cooldown
# window (i.e., the only candidate allowed by the constraint is too recent).
#
# Release timeline (all times UTC):
#
#   pbr 7.0.3         2025-11-03  (pinned by constraint; blocked by cooldown)
#
# We pin pbr==7.0.3 via a constraints file and set --pypi-min-age to the age
# of pbr 7.0.3 plus a 1-day buffer, so pbr 7.0.3 is always just inside the
# cooldown window.  Because the constraint eliminates all other pbr candidates,
# the resolver has no valid version to select and must fail.
#
# The expected error message confirms that fromager correctly identifies the
# cooldown as the cause of the resolution failure rather than emitting a
# generic "no match found" error.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Compute min-age: days since pbr 7.0.3 was published, plus a buffer.
# pbr 7.0.3 was released 2025-11-03; adding 1 day ensures it is always
# just inside the cooldown window regardless of when the test runs.
MIN_AGE=$(python3 -c "
from datetime import date
age = (date.today() - date(2025, 11, 3)).days
print(age + 1)
")

constraints_file=$(mktemp)
trap "rm -f $constraints_file" EXIT
echo "pbr==7.0.3" > "$constraints_file"

fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --constraints-file="$constraints_file" \
  --pypi-min-age="$MIN_AGE" \
  bootstrap 'stevedore' || true

pass=true

# The resolver must fail with a message identifying pbr and the cooldown as the cause.
if ! grep -q "candidate(s) for pbr.*but all were published within the last.*days (PyPI cooldown" "$OUTDIR/fromager-errors.log"; then
  echo "FAIL: expected pbr cooldown error in fromager-errors.log but did not find it" 1>&2
  pass=false
fi

$pass
