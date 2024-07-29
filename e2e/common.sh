#!/usr/bin/bash

set -x
set -e
set -u
set -o pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
OUTDIR="$(dirname "$SCRIPTDIR")/e2e-output"

rm -rf "$OUTDIR"
mkdir "$OUTDIR"
OUTDIR=$(cd "$OUTDIR" && pwd)

tox -e e2e -n -r
source .tox/e2e/bin/activate

HTTP_SERVER_PID=""
on_exit() {
    if [ -n "$HTTP_SERVER_PID" ]; then
        kill "$HTTP_SERVER_PID"
    fi
}
trap on_exit EXIT SIGINT SIGTERM

export FROMAGER_CONSTRAINTS_FILE="${SCRIPTDIR}/constraints.txt"

start_local_wheel_server() {
    # Start a web server for the wheels-repo. We remember the PID so we
    # can stop it later, and we determine the primary IP of the host
    # because podman won't see the server via localhost.
    python3 -m http.server --directory "$OUTDIR/wheels-repo/" 9999 &
    HTTP_SERVER_PID=$!
    if which ip 2>&1 >/dev/null; then
        # Linux
        IP=$(ip route get 1.1.1.1 | grep 1.1.1.1 | awk '{print $7}')
    else
        # macOS
        IP=$(ipconfig getifaddr en0)
    fi
    export WHEEL_SERVER_URL="http://${IP}:9999/simple"
}