#!/bin/bash

set -x
set -ue -o pipefail

source /venv/bin/activate

python3 -m mirror_builder \
        --wheel-server-url "$WHEEL_SERVER_URL" \
        -v \
        --work-dir $(pwd) \
        --sdists-repo /sdists-repo \
        --wheels-repo /wheels-repo \
        build "$DIST" "$VERSION" /work-dir/${DIST}*/${DIST}* \
        2>&1 | tee /build-logs/build.log

tar cvf /work-dir/built-artifacts.tar /wheels-repo/build /sdists-repo/downloads /build-logs
