#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck disable=SC1091
source "${SCRIPTDIR}/common.sh"
TOPDIR="$( cd "${SCRIPTDIR}/.." && pwd )"

toplevel=${1:-langchain}

WORKDIR=$(pwd)/work-dir-${PYTHON_VERSION}
export WORKDIR
mkdir -p "$WORKDIR"

./mirror-sdists.sh "${toplevel}"

find wheels-repo/simple/ -name '*.whl'

./install-from-mirror.sh "${toplevel}"
