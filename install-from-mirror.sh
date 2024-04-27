#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck disable=SC1091
source "$SCRIPTDIR/common.sh"

mkdir -p "$WORKDIR"

# Redirect stdout/stderr to logfile
logfile="$WORKDIR/install-mirror-${PYTHON_VERSION}.log"
exec > >(tee "$logfile") 2>&1

VENV=$(basename "$(mktemp --dry-run --directory --tmpdir=. venvXXXX)")
HTTP_SERVER_PID=""
TEST_INDEX_NAME="test"
TEST_SERVER_BASE_URL="http://localhost:3141"
TEST_INDEX_URL="${TEST_SERVER_BASE_URL}/root/${TEST_INDEX_NAME}/+simple/"
TEST_SERVER_DIR="$WORKDIR/devpi-serving-dir"

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
  pip install devpi

  # Recreate any past package index directory
  rm -rf "$TEST_SERVER_DIR"
  devpi-init --serverdir "$TEST_SERVER_DIR" --no-root-pypi
  devpi-server --serverdir "$TEST_SERVER_DIR" &
  HTTP_SERVER_PID=$!

  # Wait for the server to be available
  tries=3
  while [[ "$tries" -gt 0 ]]; do
      if curl "$TEST_SERVER_BASE_URL" >/dev/null 2>&1; then
          break
      fi
      sleep 1
  done

  # Upload all of the wheels to make them available
  devpi use "$TEST_SERVER_BASE_URL"
  devpi login root --password ''  # not secured by default
  devpi index --create "$TEST_INDEX_NAME"
  for wheel_file in wheels-repo/downloads/*.whl; do
      devpi upload --index "$TEST_INDEX_NAME" "$wheel_file"
  done
}

setup

toplevel=${1:-langchain}

pip -vvv install \
    --disable-pip-version-check \
    --no-cache-dir \
    --index-url "$TEST_INDEX_URL" \
    --upgrade \
    "${toplevel}"
pip freeze

# --dry-run --ignore-installed --report report.json
