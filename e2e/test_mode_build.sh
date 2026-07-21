#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test --test-mode with a package that fails to build (no prebuilt fallback)
# Creates a local sdist from a fixture that intentionally fails during wheel
# build and serves it via the wheel server. Since the package is not on PyPI,
# prebuilt fallback also fails and the failure is recorded.
# See: https://github.com/python-wheel-build/fromager/issues/895

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"
pass=true

DIST="test-build-failure"
VER="1.0.0"
FIXTURE_DIR="$SCRIPTDIR/test_build_failure"

# Build a sdist tarball from the fixture
SDIST_NAME="test_build_failure-${VER}"
SDIST_TARBALL="${SDIST_NAME}.tar.gz"
SDIST_STAGING=$(mktemp -d)
# Clean up staging dir on exit (common.sh already traps for on_exit)
trap 'rm -rf "$SDIST_STAGING"' EXIT

mkdir -p "$SDIST_STAGING/$SDIST_NAME"
cp -r "$FIXTURE_DIR"/* "$SDIST_STAGING/$SDIST_NAME/"
cat > "$SDIST_STAGING/$SDIST_NAME/PKG-INFO" << EOF
Metadata-Version: 2.1
Name: test_build_failure
Version: ${VER}
Summary: Test fixture that intentionally fails to build
EOF
tar -czf "$SDIST_STAGING/$SDIST_TARBALL" -C "$SDIST_STAGING" "$SDIST_NAME"

# Set up local index with the fixture tarball
# The wheel server basedir is wheels-repo/simple, so layout is:
# local-index/simple/<project>/<file>
LOCAL_INDEX="$OUTDIR/local-index"
mkdir -p "$LOCAL_INDEX/simple/$DIST"
cp "$SDIST_STAGING/$SDIST_TARBALL" "$LOCAL_INDEX/simple/$DIST/"

# Start the wheel server to serve the local index
start_local_wheel_server "$LOCAL_INDEX"

# Configure fromager to resolve from local server
mkdir -p "$OUTDIR/settings"
cat > "$OUTDIR/settings/test_build_failure.yaml" << EOF
resolver_dist:
  sdist_server_url: "${WHEEL_SERVER_URL}"
  include_sdists: true
  include_wheels: false
EOF

set +e
fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$OUTDIR/settings" \
  bootstrap --test-mode "${DIST}==${VER}"
exit_code=$?
set -e

if [ "$exit_code" -ne 1 ]; then
  echo "FAIL: expected exit code 1, got $exit_code" 1>&2
  pass=false
fi

failures_file=$(find "$OUTDIR/work-dir" -name "test-mode-failures-*.json" 2>/dev/null | head -1)

if [ -z "$failures_file" ]; then
  echo "FAIL: no test-mode-failures JSON file found" 1>&2
  pass=false
else
  # The package name in the JSON is the canonicalized name
  if ! jq -e '.failures[] | select(.package == "test-build-failure")' "$failures_file" >/dev/null 2>&1; then
    echo "FAIL: test-build-failure not found in failures" 1>&2
    pass=false
  fi

  # Must be 'bootstrap' failure (actual build failure, not resolution)
  failure_type=$(jq -r '[.failures[] | select(.package == "test-build-failure")][0].failure_type' "$failures_file")
  if [ "$failure_type" != "bootstrap" ]; then
    echo "FAIL: expected failure_type 'bootstrap', got '$failure_type'" 1>&2
    pass=false
  fi
fi

if ! grep -q "test mode enabled" "$OUTDIR/bootstrap.log"; then
  echo "FAIL: 'test mode enabled' not in log" 1>&2
  pass=false
fi

$pass
