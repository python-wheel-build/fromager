#!/bin/bash

set -x
set -e
set -o pipefail

toplevel=${1:-langchain}

PYTHON_TO_TEST="
  python3.9
  python3.12
"

for PYTHON in $PYTHON_TO_TEST; do
    PYTHON=$PYTHON ./mirror-sdists.sh "${toplevel}"
    if PYTHON=$PYTHON ./install-from-mirror.sh "${toplevel}"; then
        echo "SUCCESS $PYTHON"
    else
        echo "FAIL $PYTHON"
    fi
done
