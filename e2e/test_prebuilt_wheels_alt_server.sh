#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test that when resolving a pre-built wheel the --wheel-server-url is
# given preference over PyPI.org.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

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

start_local_wheel_server "$INIT/wheels-repo"

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

TESTDIR="$OUTDIR/test"
mkdir -p "$TESTDIR"
cd "$TESTDIR"

mkdir -p $TESTDIR/overrides/settings
cat - > $TESTDIR/overrides/settings/flit_core.yaml <<EOF
variants:
  cpu:
    pre_built: True
EOF

# Bootstrap the package we modified, and another that we don't have on
# the local server.
fromager \
  -v \
  --wheel-server-url "$WHEEL_SERVER_URL" \
  --settings-dir="$TESTDIR/overrides/settings" \
  bootstrap "${DIST}==${VERSION}" "wheel==0.43.0"

# Ensure we have both expected wheels
EXPECTED_FILES="
wheels-repo/prebuilt/flit_core-3.9.0-0-py3-none-any.whl
wheels-repo/downloads/wheel-0.43.0-0-py3-none-any.whl
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
