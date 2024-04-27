#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

set -eux
set -o pipefail

# shellcheck disable=SC1091
source /venv/bin/activate

python3 -m mirror_builder \
        --wheel-server-url "$WHEEL_SERVER_URL" \
        -v \
        --work-dir /work-dir \
        --sdists-repo /sdists-repo \
        --wheels-repo /wheels-repo \
        build "$DIST" "$VERSION" \
        2>&1 | tee /build-logs/build.log

tar cvf /work-dir/built-artifacts.tar /wheels-repo/build /sdists-repo/downloads /build-logs
