#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests that --min-release-age applies to packages resolved through the
# GitLabTagProvider, verifying that the cooldown uses GitLab tag commit
# timestamps.
#
# The python-gitlab package is a good candidate because it is hosted on
# gitlab.com, is pure Python, and has a well-documented release history.
#
# Release timeline (all times UTC):
#
#   python-gitlab v5.0.0   2024-10-28  (the expected fallback)
#   python-gitlab v5.1.0   2024-11-28  (blocked by cooldown — the anchor date)
#   python-gitlab v5.2.0+  2024-12-17+ (all blocked by cooldown)
#
# We compute --min-release-age dynamically as the age of v5.1.0 in days plus a
# 1-day buffer.  This places the cutoff just before 2024-11-28, blocking v5.1.0
# and all later releases while allowing v5.0.0 (released ~31 days earlier).
#
# Anchoring to v5.1.0 (2024-11-28) ensures the build toolchain can use
# flit_core 3.10.0 (released 2024-10-31), which is required for Python 3.14
# compatibility.
#
# The gitlab_override_example plugin (installed below) registers a
# get_resolver_provider hook that returns a GitLabTagProvider for python-gitlab,
# routing resolution through the GitLab tag API instead of PyPI.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# Install the override plugin that routes python-gitlab through GitLabTagProvider.
# Uninstall on exit so its entry points don't leak into subsequent e2e tests.
trap 'python3 -m pip uninstall -y gitlab_override_example >/dev/null 2>&1 || true' EXIT
pip install "$SCRIPTDIR/gitlab_override_example"

# Compute min-age: days since python-gitlab v5.1.0 was tagged, plus a buffer.
# v5.1.0 was tagged 2024-11-28; adding 1 day ensures it is always just inside
# the cooldown window regardless of when the test runs.
MIN_AGE=$(python3 -c "
from datetime import date
age = (date.today() - date(2024, 11, 28)).days
print(age + 1)
")

fromager \
  --debug \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --min-release-age="$MIN_AGE" \
  bootstrap 'python-gitlab'

find "$OUTDIR/wheels-repo/" -name '*.whl'

pass=true

# v5.1.0 is blocked by the cooldown; the resolver must fall back to v5.0.0.
if ! find "$OUTDIR/wheels-repo/downloads/" -name 'python_gitlab-5.0.0*.whl' | grep -q .; then
  echo "FAIL: python_gitlab-5.0.0 wheel not found — cooldown did not force fallback" 1>&2
  pass=false
fi

# Confirm newer versions were rejected by the cooldown.
if find "$OUTDIR/wheels-repo/downloads/" -name 'python_gitlab-5.[1-9]*.whl' | grep -q .; then
  echo "FAIL: a python_gitlab wheel newer than 5.0.0 was selected despite the cooldown" 1>&2
  pass=false
fi

# Confirm the GitLabTagProvider was actually used (not the default PyPI provider).
if ! grep -q "GitLabTagProvider" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: GitLabTagProvider was not used for resolution" 1>&2
  pass=false
fi

$pass
