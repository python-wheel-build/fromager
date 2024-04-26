#!/bin/bash

set -xe
set -o pipefail

DIST="$1"
VERSION="$2"

if [ -z "$DIST" ]; then
    usage "Specify a DIST to build"
    exit 1
fi
if [ -z "$VERSION" ]; then
    usage "Specify the version of $DIST to build"
    exit 1
fi

export PYTHON=${PYTHON:-python3.11}

DEFAULT_WORKDIR="$(pwd)/work-dir"
export WORKDIR="${WORKDIR:-${DEFAULT_WORKDIR}}"
mkdir -p "$WORKDIR"

mkdir -p sdists-repo
mkdir -p "${WORKDIR}"
mkdir -p build-logs

VENV="${WORKDIR}/venv-onboard-sdist"
if [ -d "$VENV" ]; then
    # shellcheck disable=SC1091
    source "${VENV}/bin/activate"
else
    "${PYTHON}" -m venv "${VENV}"
    # shellcheck disable=SC1091
    source "${VENV}/bin/activate"
    pip install --upgrade pip
    pip install -e .
fi

# Download the source archive
python3 -m mirror_builder \
        --log-file build-logs/download-source-archive.log \
        --work-dir "$WORKDIR" \
        --sdists-repo sdists-repo \
        --wheels-repo wheels-repo \
        download-source-archive "${DIST}" "${VERSION}"
