#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test that when resolving a pre-built wheel the --wheel-server-url is
# given preference over PyPI.org.

set -x
set -e
set -o pipefail

on_exit() {
  [ "$HTTP_SERVER_PID" ] && kill "$HTTP_SERVER_PID"
}
trap on_exit EXIT SIGINT SIGTERM

OUTDIR="$(dirname "$SCRIPTDIR")/e2e-output"

rm -rf "$OUTDIR"
mkdir "$OUTDIR"
OUTDIR="$(cd "$OUTDIR" && pwd)"  # use full path so when we cd we can still find things

tox -e e2e -n -r
source .tox/e2e/bin/activate

INIT="$OUTDIR/init"
mkdir -p "$INIT"

# What are we building?
DIST="flit_core"
VERSION="3.9.0"

# Get the wheel we need from PyPI
fromager \
  --sdists-repo="$INIT/sdists-repo" \
  --wheels-repo="$INIT/wheels-repo" \
  --work-dir="$INIT/work-dir" \
  bootstrap "${DIST}==${VERSION}"

# Modify the wheel so we can identify it as coming from the right
# server.
cd "$OUTDIR"
mkdir tmp
cp "$INIT"/wheels-repo/downloads/flit_core*.whl tmp
cd tmp
unzip flit_core*.whl
echo "Test was here" > flit_core*.dist-info/LICENSE
filename=$(echo flit_core*.whl)
rm "$filename"
zip -r "$filename" flit_core*
cp "$filename" "$INIT/wheels-repo/downloads"

# Make sure the mirror is up to date
pypi-mirror create -d "$INIT/wheels-repo/downloads/" -m "$INIT/wheels-repo/simple/"

# Start a web server for the wheels-repo. We remember the PID so we
# can stop it later, and we determine the primary IP of the host
# because podman won't see the server via localhost.
python3 -m http.server --directory "$INIT/wheels-repo/" 9999 &
HTTP_SERVER_PID=$!
IP=$(ip route get 1.1.1.1 | grep 1.1.1.1 | awk '{print $7}')
export WHEEL_SERVER_URL="http://${IP}:9999/simple"

TESTDIR="$OUTDIR/test"
mkdir -p "$TESTDIR"
cd "$TESTDIR"

mkdir overrides
cat - >overrides/settings.yaml <<EOF
pre_built:
  cpu:
    - flit_core
EOF

# Bootstrap the package we modified, and another that we don't have on
# the local server.
fromager \
  -v \
  --wheel-server-url "$WHEEL_SERVER_URL" \
  bootstrap "${DIST}==${VERSION}" "wheel==0.43.0"

# Ensure we have both expected wheels
EXPECTED_FILES="
wheels-repo/prebuilt/flit_core-3.9.0-py3-none-any.whl
wheels-repo/downloads/wheel-0.43.0-py3-none-any.whl
"

pass=true
for f in $EXPECTED_FILES; do
  if [ ! -f "$f" ]; then
    echo "FAIL: Did not find $OUTDIR/$f" 1>&2
    pass=false
  fi
done

# Ensure we got the right copy of the wheel for flit_core, with the
# modified license file.
cd wheels-repo/prebuilt
unzip "$filename"
cat flit_core*.dist-info/LICENSE
if ! grep -q "Test was here" flit_core*.dist-info/LICENSE; then
  echo "FAIL: Did not found expected text"
  pass=false
fi

$pass
