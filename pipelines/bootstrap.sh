#!/bin/bash

set -xe
set -o pipefail

TOPLEVEL="${1}"
if [ -z "$TOPLEVEL" ]; then
    echo "Usage: $0 TOPLEVEL" 1>&2
    echo "ERROR: No toplevel package specified." 1>&2
    exit 1
fi

PYTHON=${PYTHON:-python3.11}

DEFAULT_WORKDIR=$(realpath "$(pwd)/work-dir")
WORKDIR=${WORKDIR:-${DEFAULT_WORKDIR}}
mkdir -p "$WORKDIR"

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
python3 -m mirror_builder ${VERBOSE} \
        --log-file "$WORKDIR/bootstrap.log" \
        bootstrap "${TOPLEVEL}"
