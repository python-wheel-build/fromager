#!/usr/bin/bash

set -x
set -e
set -u
set -o pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
OUTDIR="$(dirname "$SCRIPTDIR")/e2e-output"

# coverage reporting
export COVERAGE_PROCESS_START="$( dirname "$SCRIPTDIR" )/pyproject.toml"

# Recreate output directory
rm -rf "$OUTDIR"
mkdir "$OUTDIR"

# Recompute path to output directory so it is a full path
OUTDIR=$(cd "$OUTDIR" && pwd)

# Make sure the build-logs directory exists
mkdir -p "$OUTDIR/build-logs"

# Recreate the virtualenv with fromager installed
# command_pre hook creates cov.pth
tox -e e2e -r
source .tox/e2e/bin/activate

# Set a variable to constrain packages used in the tests
export FROMAGER_CONSTRAINTS_FILE="${SCRIPTDIR}/constraints.txt"

# Local web server management
HTTP_SERVER_PID=""
on_exit() {
    if [ -n "$HTTP_SERVER_PID" ]; then
        echo "Stopping wheel server"
        kill "$HTTP_SERVER_PID"
    fi
}
trap on_exit EXIT SIGINT SIGTERM

start_local_wheel_server() {
    local serve_dir="${1:-$OUTDIR/wheels-repo/}"
    # Start a web server for the wheels-repo. We remember the PID so we
    # can stop it later, and we determine the primary IP of the host
    # because podman won't see the server via localhost.
    python3 -m http.server --directory "$serve_dir" 9999 &
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
