#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

E2E_SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TOPDIR="$( cd "${E2E_SCRIPTDIR}/.." && pwd )"
# shellcheck disable=SC1091
source "$TOPDIR/common.sh"

VERBOSE=${VERBOSE:-}
if [ -n "${VERBOSE}" ]; then
  VERBOSE="-v"
fi

setup() {
    rm -rf "${WORKDIR}"
    mkdir -p "${WORKDIR}"
}

full_clean() {
    rm -rf "${TOPDIR}/wheels-repo" "${TOPDIR}/sdists-repo"
    rm -rf "${WORKDIR}"
}

banner() {
    echo "##############################"
    echo "$*"
    echo "##############################"
}
