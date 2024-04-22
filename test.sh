#!/bin/bash

set -x
set -e
set -o pipefail

toplevel=${1:-langchain}

DEFAULT_PYTHON_TO_TEST="
  python3.11
  python3.9
  python3.12
"
PYTHON_TO_TEST=${PYTHON_TO_TEST=-${DEFAULT_PYTHON_TO_TEST}}


for PYTHON in $PYTHON_TO_TEST; do
    export PYTHON
    PYTHON_VERSION=$($PYTHON --version | cut -f2 -d' ')

    WORKDIR=$(pwd)/work-dir-${PYTHON_VERSION}
    export WORKDIR
    mkdir -p "$WORKDIR"

    ./mirror-sdists.sh "${toplevel}"

    find wheels-repo/simple/ -name '*.whl'

    ./install-from-mirror.sh "${toplevel}"
done
