#!/bin/bash

export PS4='+ ${BASH_SOURCE#$HOME/}:$LINENO \011'

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TOPDIR="$( cd "${SCRIPTDIR}/.." && pwd )"

VERBOSE=${VERBOSE:-}
if [ -n "${VERBOSE}" ]; then
  VERBOSE="-v"
fi

DEFAULT_WORKDIR=$(pwd)/work-dir
export WORKDIR=${WORKDIR:-${DEFAULT_WORKDIR}}

export PYTHON=${PYTHON:-python3.11}
PYTHON_VERSION=$($PYTHON --version | cut -f2 -d' ')
export PYTHON_VERSION

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
