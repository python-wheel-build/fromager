#!/bin/bash

set -x

VENV=$(basename $(mktemp --dry-run --directory --tmpdir=. venvXXXX))
PYTHON=python3.9
HTTP_SERVER_PID=

on_exit() {
  [ "$HTTP_SERVER_PID" ] && kill $HTTP_SERVER_PID
  rm -rf $VENV/
}
trap on_exit EXIT

setup() {
  $PYTHON -m venv $VENV
  . ./$VENV/bin/activate
  pip install -U pip
  export SITE_PKGS_DIR=$VENV/lib/$PYTHON/site-packages
}

setup

$PYTHON -m http.server &
HTTP_SERVER_PID=$!

pip install --no-cache-dir --index-url http://localhost:8000/simple -U aiohttp
