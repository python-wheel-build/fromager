#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

set -xe
set -o pipefail
export PS4='+ ${BASH_SOURCE#$HOME/}:$LINENO \011'

VERBOSE=${VERBOSE:-}
if [ -n "${VERBOSE}" ]; then
  VERBOSE="-v"
fi

DEFAULT_WORKDIR=$(realpath "$(pwd)/work-dir")
WORKDIR=${WORKDIR:-${DEFAULT_WORKDIR}}
mkdir -p "$WORKDIR"

PYTHON=${PYTHON:-python3.9}

TOPLEVEL="${1:-langchain}"

# Redirect stdout/stderr to logfile
logfile="$WORKDIR/mirror-sdists.log"
exec > >(tee "$logfile") 2>&1

VENV="${WORKDIR}/venv"
# Create a fresh virtualenv every time since the process installs
# packages into it.
rm -rf "${VENV}"
"${PYTHON}" -m venv "${VENV}"
# shellcheck disable=SC1091
source "${VENV}/bin/activate"
pip install --upgrade pip
pip install -e .

# shellcheck disable=SC2086
python3 -m mirror_builder ${VERBOSE} bootstrap "${TOPLEVEL}"
