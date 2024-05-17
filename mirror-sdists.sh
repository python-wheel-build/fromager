#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck disable=SC1091
source "$SCRIPTDIR/common.sh"

mkdir -p "$WORKDIR"

# Redirect stdout/stderr to logfile
logfile="$WORKDIR/mirror-sdists.log"
exec > >(tee "$logfile") 2>&1

TOPLEVEL="${1}"
VARIANT="${2:-cpu}"

if [ -z "$TOPLEVEL" ]; then
  echo "Usage: $0 <toplevel-requirement> [<variant>]" 1>&2
  exit 1
fi

VERBOSE=${VERBOSE:-}
if [ -n "${VERBOSE}" ]; then
  VERBOSE="-v"
fi

VENV="${WORKDIR}/venv-mirror-sdists"
install_tools "$VENV"

# shellcheck disable=SC2086
python3 -m mirror_builder ${VERBOSE} \
        --variant "$VARIANT" \
        --log-file "$WORKDIR/mirror-sdists-debug.log" \
        bootstrap "${TOPLEVEL}"
