#!/bin/bash

set -x
set -e
set -o pipefail

toplevel=${1:-langchain}

PYTHON_TO_TEST="
  python3.9
  python3.12
"

if ps -f | grep http.server | grep -q python; then
    existing_server=$(ps -f | grep http.server | grep python | awk '{print $2}')
    echo "Killing stale web server"
    kill "${existing_server}"
fi

for PYTHON in $PYTHON_TO_TEST; do
    PYTHON=$PYTHON ./mirror-sdists.sh "${toplevel}"
    PYTHON=$PYTHON ./install-from-mirror.sh "${toplevel}"
done
