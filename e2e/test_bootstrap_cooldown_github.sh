#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests that when --min-release-age is active and a package is resolved through
# the GitHubTagProvider, the cooldown is NOT enforced (because GitHub does not
# yet provide upload timestamps), but a warning is emitted for each candidate.
#
# The stevedore test repo (python-wheel-build/stevedore-test-repo) is used as
# a convenient GitHub-hosted package with known tags.
#
# MIN_AGE is anchored to stevedore 5.4.1 (2025-02-20), so it is large enough
# that enforcement WOULD block the resolved candidate — confirming that the
# GitHubTagProvider correctly skips enforcement rather than failing closed.
# Using a modest cooldown (rather than 9999 days) avoids inadvertently blocking
# PyPI build dependencies like setuptools, which are always recent.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Anchor: stevedore 5.4.1 was released 2025-02-20.
# MIN_AGE exceeds its age, so the cooldown would block it if enforced.
MIN_AGE=$(python3 -c "
from datetime import date
age = (date.today() - date(2025, 2, 20)).days
print(age + 1)
")

# Install the override plugin that routes stevedore through GitHubTagProvider.
# Uninstall on exit so its entry points don't leak into subsequent e2e tests.
trap 'python3 -m pip uninstall -y github_override_example >/dev/null 2>&1 || true' EXIT
pip install "$SCRIPTDIR/github_override_example"

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

# Resolution must succeed despite the 9999-day cooldown — GitHub timestamps
# are not yet supported, so the cooldown is skipped rather than enforced.
if ! find "$OUTDIR/wheels-repo/downloads/" -name 'stevedore-*.whl' | grep -q .; then
  echo "FAIL: no stevedore wheel found — resolution should have succeeded despite cooldown" 1>&2
  pass=false
fi

# A warning must be emitted explaining why the cooldown was skipped.
if ! grep -q "not yet implemented" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: expected cooldown-skipped warning not found in log" 1>&2
  pass=false
fi

$pass
