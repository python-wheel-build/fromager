#!/bin/bash

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck disable=SC1091
TOPDIR="$( cd "${SCRIPTDIR}/.." && pwd )"
# shellcheck disable=SC1091
source "$TOPDIR/common.sh"

TOPLEVEL="${1}"
if [ -z "$TOPLEVEL" ]; then
    echo "Usage: $0 TOPLEVEL" 1>&2
    echo "ERROR: No toplevel package specified." 1>&2
    exit 1
fi

mkdir -p "$WORKDIR"

VENV="${WORKDIR}/venv"
install_tools "$VENV"

# shellcheck disable=SC2086
python3 -m mirror_builder ${VERBOSE} \
        --log-file "$WORKDIR/bootstrap.log" \
        bootstrap "${TOPLEVEL}"
