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