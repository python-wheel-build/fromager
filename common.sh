#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

set -xe
set -o pipefail
export PS4='+ ${BASH_SOURCE#$HOME/}:$LINENO \011'

export PYTHON="${PYTHON:-python3.11}"
PYTHON_VERSION=$("$PYTHON" --version | cut -f2 -d' ')
export PYTHON_VERSION

DEFAULT_WORKDIR=$(pwd)/work-dir
export WORKDIR="${WORKDIR:-${DEFAULT_WORKDIR}}"

# Index server where we have packages with the tools used by this
# repo.
export TOOL_SERVER_URL=https://pyai.fedorainfracloud.org/internal/tools/+simple/

# Index server where we have sdists for the software we are building.
export SDIST_SERVER_URL=https://pyai.fedorainfracloud.org/experimental/sources/+simple/

# Set a default URL until we have our private one running.
export WHEEL_SERVER_URL=${WHEEL_SERVER_URL:-https://pypi.org/simple}

install_tools() {
  local -r venv="$1"

  # Create a fresh virtualenv every time since the process installs
  # packages into it.
  rm -rf "${venv}"

  "${PYTHON}" -m venv "${venv}"
  # shellcheck disable=SC1091
  source "${venv}/bin/activate"
  pip install \
      --disable-pip-version-check \
      --no-cache-dir \
      --index-url "$TOOL_SERVER_URL" \
      -e "$(dirname "${BASH_SOURCE[0]}")"
}
