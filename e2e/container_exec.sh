#!/bin/bash
#
# We could build the virtualenv inside the container, but then we
# can't install anything into it, which we need to be able to do at
# runtime. Therefore we want to build it as we run commands in the
# container, and we want to preserve it across container runs. So, we
# put it outside the container in the work directory and use this
# script as a wrapper for commands we run inside the container that
# need the virtualenv to ensure it exists at the right time and to
# update PATH before running any other commands.

set -ue -o pipefail

echo "${PATH}"

VERBOSE=${VERBOSE:-}
if [ -n "${VERBOSE}" ]; then
  VERBOSE="-v"
fi

# Make sure we have the virtualenv and it is active. We don't use the
# install_tools function in common.sh because it always recreates the
# environment and we want to retain it between runs.
VENV="${WORKDIR}/venv-${PYTHON}"
if [ ! -d "${VENV}" ]; then
    "${PYTHON}" -m venv "${VENV}"
    # shellcheck disable=SC1091
    source "${VENV}/bin/activate"
    pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        --index-url "$TOOL_SERVER_URL" \
        -e .
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

python3 -m mirror_builder \
        "${VERBOSE}" \
        --work-dir "${WORKDIR}" \
        --sdists-repo /sdists-repo \
        --wheels-repo /wheels-repo \
        "$@"
