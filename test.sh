#!/bin/bash

set -x
set -e
set -o pipefail

toplevel=${1:-langchain}

rm -rf sdists-repo wheels-repo .build* work-dir
./mirror-sdists.sh "${toplevel}"

./install-from-mirror.sh "${toplevel}"
