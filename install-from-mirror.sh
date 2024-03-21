#!/bin/bash

set -xe

# Redirect stdout/stderr to logfile
logfile=".install_from_mirror_$(date '+%Y-%m-%d_%H-%M-%S').log"
exec > >(tee "$logfile") 2>&1

VENV=$(basename $(mktemp --dry-run --directory --tmpdir=. venvXXXX))
PYTHON=python3.9
HTTP_SERVER_PID=

on_exit() {
  [ "$HTTP_SERVER_PID" ] && kill $HTTP_SERVER_PID
  rm -rf $VENV/
}
trap on_exit EXIT SIGINT SIGTERM

setup() {
  $PYTHON -m venv $VENV
  . ./$VENV/bin/activate
  pip install -U pip
}

setup

$PYTHON -m http.server &
HTTP_SERVER_PID=$!

pip -vvv install --no-cache-dir --index-url http://localhost:8000/simple -U langchain

# --dry-run --ignore-installed --report report.json
