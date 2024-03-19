#!/bin/bash

set -xe

# Redirect stdout/stderr to logfile
logfile=".build_wheels_$(date '+%Y-%m-%d_%H-%M-%S').log"
exec > >(tee "$logfile") 2>&1

VENV=$(basename $(mktemp --dry-run --directory --tmpdir=. venvXXXX))
PYTHON=python3.9
HTTP_SERVER_PID=
WHEEL_BUILD_TMPDIR=

on_exit() {
  [ "$HTTP_SERVER_PID" ] && kill $HTTP_SERVER_PID
  [ $WHEEL_BUILD_TMPDIR ] && rm -rf $WHEEL_BUILD_TMPDIR
  rm -rf $VENV/
}
trap on_exit EXIT

setup() {
  $PYTHON -m venv $VENV
  . ./$VENV/bin/activate
  pip install -U pip
}

setup

pip install -U python-pypi-mirror

WHEELS_REPO=$(realpath $(pwd)/wheels-repo)

rm -rf "${WHEELS_REPO}"
mkdir -p "${WHEELS_REPO}/downloads"

update_mirror() {
  pypi-mirror create -d "${WHEELS_REPO}/downloads" -m "${WHEELS_REPO}/simple"
}

update_mirror
$PYTHON -m http.server -d "${WHEELS_REPO}" &
HTTP_SERVER_PID=$!

build_wheel() {
  local pkg="$1"; shift

  WHEEL_BUILD_TMPDIR=$(mktemp --tmpdir=. --directory wheelbuildXXXX)
  pushd $WHEEL_BUILD_TMPDIR

  # FIXME: --no-cache-dir should be sufficient, but I don't trust it yet!
  rm -rf ~/.cache/pip

  # FIXME: this sdist should be downloaded in advance, outside of this script
  local sdist=$(pip download --no-deps --no-binary :all: "${pkg}" | grep Saved | cut -d ' ' -f 2-)

  pip -vvv --disable-pip-version-check wheel --index-url http://localhost:8000/simple ${sdist}

  # FIXME: this should only ever be one wheel?
  mv *.whl "${WHEELS_REPO}/downloads"
  update_mirror

  popd
  rm -rf $WHEEL_BUILD_TMPDIR; WHEEL_BUILD_TMPDIR=
}

jq -r '.[].req' sdists-repo/build-order.json | \
  while read -r p; do
    build_wheel "${p}"
  done
