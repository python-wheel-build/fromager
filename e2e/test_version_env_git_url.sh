#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test that ${__version__} in env settings fails when bootstrapping from
# a git URL without a PEP 440 version tag, and succeeds when a fallback
# default is provided via ${__version__:-...}.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

GIT_REPO_URL="https://github.com/python-wheel-build/stevedore-test-repo.git"

pass=true

# --- Part 1: ${__version__} WITHOUT default should fail ---

echo "=== Part 1: expect failure with \${__version__} (no default) ==="

if fromager \
    --log-file="$OUTDIR/bootstrap-no-default.log" \
    --error-log-file="$OUTDIR/fromager-errors-no-default.log" \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/wheels-repo" \
    --work-dir="$OUTDIR/work-dir" \
    --settings-dir="$SCRIPTDIR/version_env_settings_no_default" \
    bootstrap "stevedore @ git+${GIT_REPO_URL}" 2>&1; then
  echo "FAIL: bootstrap with \${__version__} (no default) should have failed" 1>&2
  pass=false
else
  echo "OK: bootstrap with \${__version__} (no default) failed as expected"
  if grep -q "__version__" "$OUTDIR/fromager-errors-no-default.log" 2>/dev/null || \
     grep -q "__version__" "$OUTDIR/bootstrap-no-default.log" 2>/dev/null; then
    echo "OK: error message mentions __version__"
  else
    echo "WARN: error log does not mention __version__; check logs manually"
  fi
fi

# --- Part 2: ${__version__:-unresolved} WITH default should succeed ---

echo "=== Part 2: expect success with \${__version__:-unresolved} ==="

rm -rf "$OUTDIR/work-dir" "$OUTDIR/sdists-repo" "$OUTDIR/wheels-repo"
mkdir -p "$OUTDIR/build-logs"

fromager \
    --log-file="$OUTDIR/bootstrap-with-default.log" \
    --error-log-file="$OUTDIR/fromager-errors-with-default.log" \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/wheels-repo" \
    --work-dir="$OUTDIR/work-dir" \
    --settings-dir="$SCRIPTDIR/version_env_settings_with_default" \
    bootstrap "stevedore @ git+${GIT_REPO_URL}"

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/stevedore-*.whl
$OUTDIR/sdists-repo/builds/stevedore-*.tar.gz
"

for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "FAIL: Did not find $pattern" 1>&2
    pass=false
  fi
done

$pass
