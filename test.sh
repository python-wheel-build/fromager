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
    PYTHON=$PYTHON ./mirror-sdists.sh "${toplevel}"
    find wheels-repo/simple/ -name '*.whl'
    PYTHON=$PYTHON ./install-from-mirror.sh "${toplevel}"
done
