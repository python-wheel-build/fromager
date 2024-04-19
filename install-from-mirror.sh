#!/bin/bash

set -xe

DEFAULT_WORKDIR=$(realpath "$(pwd)/work-dir")
WORKDIR=${WORKDIR:-${DEFAULT_WORKDIR}}
mkdir -p "$WORKDIR"

PYTHON=${PYTHON:-python3.9}

# Redirect stdout/stderr to logfile
logfile="$WORKDIR/install-mirror-${PYTHON_VERSION}.log"
exec > >(tee "$logfile") 2>&1

VENV=$(basename "$(mktemp --dry-run --directory --tmpdir=. venvXXXX)")
HTTP_SERVER_PID=

on_exit() {
  [ "$HTTP_SERVER_PID" ] && kill $HTTP_SERVER_PID
  rm -rf "${VENV:?}"
}
trap on_exit EXIT SIGINT SIGTERM

setup() {
  $PYTHON -m venv "${VENV}"
  # shellcheck disable=SC1090
  . "./$VENV/bin/activate"
  pip install -U pip
}

setup

toplevel=${1:-langchain}

$PYTHON -m http.server --directory wheels-repo/ 9090 &
HTTP_SERVER_PID=$!

pip -vvv install \
    --disable-pip-version-check \
    --no-cache-dir \
    --index-url http://localhost:9090/simple \
    --upgrade \
    "${toplevel}"
pip freeze

# --dry-run --ignore-installed --report report.json
