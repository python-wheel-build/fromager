#!/bin/bash

set -x
set -e
set -o pipefail

DEFAULT_WORKDIR="$(pwd)/work-dir"
export WORKDIR="${WORKDIR:-${DEFAULT_WORKDIR}}"
mkdir -p "$WORKDIR"

export PYTHON=${PYTHON:-python3.11}

VENV="${WORKDIR}/venv-twine"
if [ -d "$VENV" ]; then
    # shellcheck disable=SC1091
    source "${VENV}/bin/activate"
else
    "${PYTHON}" -m venv "${VENV}"
    # shellcheck disable=SC1091
    source "${VENV}/bin/activate"
    pip install --upgrade pip
    pip install twine
fi

# We use a consistent target name so we can pass different config
# files into the job to upload to different indexes without needing 2
# variables.
INDEX=${INDEX:-upload-target}

# The config file in the pipeline comes from the secret and is a fully
# formed pypirc file. It's dropped somewhere random and the path is
# passed here. The default allows a developer to put a similar file in
# their local directory for regular use and testing, without modifying
# their global ~/.pypirc.
CONFIG=${CONFIG:-.pypirc}

twine upload \
      --non-interactive \
      --disable-progress-bar \
      --repository "$INDEX" \
      --config-file "$CONFIG" \
      "$@"
