#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test that we can build flit_core, a low-level dependency for which
# we know there are no other dependencies and for which we have an
# override for how to do the actual wheel build.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck disable=SC1091
source "${SCRIPTDIR}/common.sh"
TOPDIR="$( cd "${SCRIPTDIR}/.." && pwd )"

# Pre-cleaning
rm -rf artifacts

# Build flit_core. We know this doesn't require anything else.
"${TOPDIR}/build_wheel.sh" -d flit_core -v 3.9.0

if [ ! -f artifacts/built-artifacts.tar ]; then
  echo "Did not find built-artifacts.tar" 1>&2
  exit 1
fi

tar -C artifacts -xvf artifacts/built-artifacts.tar

EXPECTED_FILES="
wheels-repo/build/flit_core-3.9.0-py3-none-any.whl
sdists-repo/downloads/flit_core-3.9.0.tar.gz
build-logs/flit-core-build.log
build-logs/flit-core-prepare-build.log
build-logs/flit-core-prepare-source.log
build-logs/flit-core-download-source-archive.log
"

pass=true
for f in $EXPECTED_FILES; do
  if [ ! -f "artifacts/$f" ]; then
    echo "Did not find $f" 1>&2
    pass=false
  fi
done
$pass
