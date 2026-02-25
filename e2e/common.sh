#!/usr/bin/bash

set -x
set -e
set -u
set -o pipefail

export PS4='+(${BASH_SOURCE}:${LINENO}): ${FUNCNAME[0]:+${FUNCNAME[0]}(): }'

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
# tox -e e2e -r
# source .tox/e2e/bin/activate
hatch env remove e2e || true # Remove the e2e env if it exists, ignore error if it doesn't
hatch env create e2e # Ensures the environment exists and dependencies are installed
if [ ! -f .skip-coverage ]; then
    hatch run e2e:setup-cov # Run the coverage setup script
else
    echo "Skipping coverage setup"
fi
source "$(hatch env find e2e)/bin/activate"

# Set a variable to constrain packages used in the tests
export FROMAGER_CONSTRAINTS_FILE="${SCRIPTDIR}/constraints.txt"

OS=$(uname)
if [ "$OS" = "Darwin" ]; then
    NETWORK_ISOLATION=""
    # The tag comes back as something like "macosx-10.9-universal2" but the
    # filename contains "macosx_10_9_universal2".
    WHEEL_PLATFORM_TAG=$(python3 -c 'import sysconfig; print(sysconfig.get_platform().replace("-", "_").replace(".", "_"))')
    HAS_ELFDEP="0"
else
    NETWORK_ISOLATION="--network-isolation"
    WHEEL_PLATFORM_TAG="linux_x86_64"
    HAS_ELFDEP="1"
fi
export NETWORK_ISOLATION
export WHEEL_PLATFORM_TAG
export HAS_ELFDEP

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
        # Linux: need host IP because podman can't reach localhost
        IP=$(ip route get 1.1.1.1 | grep 1.1.1.1 | awk '{print $7}')
    else
        # macOS: no network isolation, localhost works
        IP=127.0.0.1
    fi
    export WHEEL_SERVER_URL="http://${IP}:9999/simple"

    # Wait for the server to accept connections (up to 15 s).
    { set +x; } 2>/dev/null
    local ready=false
    for _ in $(seq 1 30); do
        kill -0 "$HTTP_SERVER_PID" 2>/dev/null || break
        curl -sf "http://${IP}:9999/" >/dev/null 2>&1 && { ready=true; break; }
        sleep 0.5
    done
    set -x

    if $ready; then
        echo "Wheel server is ready"
        return 0
    fi
    echo "ERROR: wheel server did not become ready" >&2
    return 1
}
