#!/bin/bash

set -x
set -e
set -o pipefail

toplevel=${1:-langchain}

PYTHON_TO_TEST="
  python3.9
  python3.12
"

WORKDIR=$(realpath $(pwd)/work-dir)
mkdir -p $WORKDIR

for PYTHON in $PYTHON_TO_TEST; do

    VENV="${WORKDIR}/venv-${PYTHON}"
    # Create a fresh virtualenv every time since the process installs
    # packages into it.
    rm -rf "${VENV}"
    "${PYTHON}" -m venv "${VENV}"
    source "${VENV}/bin/activate"
    pip install --upgrade pip
    pip install -r requirements.txt
    python3 -m mirror_builder "${toplevel}" 2>&1 | tee work-dir/mirror_builder-${PYTHON}.log

    PYTHON=$PYTHON ./install-from-mirror.sh "${toplevel}"
done
