#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

set -xe
set -o pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck disable=SC1091
TOPDIR="$( cd "${SCRIPTDIR}/.." && pwd )"
# shellcheck disable=SC1091
source "$TOPDIR/common.sh"

rm -rf work-dir sdists-repo wheels-repo build artifacts
mkdir build-logs

for python_version in python3.11 python3.12; do
  for dependency in devpi twine; do
    export PYTHON=$python_version
    "${TOPDIR}/mirror-sdists.sh" "$dependency"
    # Preserve the logs as artifacts in case of an issue
    mkdir -p "build-logs/$dependency"
    cp work-dir/*.log "build-logs/$dependency/"
  done
done
