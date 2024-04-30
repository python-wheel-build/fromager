#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Create a separate work dir so we can save the output to compare to
# what we get when we run the same scripts outside of the
# container. Set this before loading common.sh to override the default
# consistently.
WORKDIR=$(pwd)/work-dir-container

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck disable=SC1091
source "$SCRIPTDIR/common.sh"

mkdir -p "$WORKDIR"

logfile="$WORKDIR/test-container-${PYTHON}.log"
exec > >(tee "$logfile") 2>&1

TOPLEVEL="${1:-langchain}"

in_container() {
    podman run -it --rm \
           -e PYTHON="$PYTHON" \
           -e WORKDIR=/work-dir \
           -e VERBOSE=true \
           --userns=keep-id \
           --security-opt label=disable \
           --volume .:/src:rw,exec \
           --volume "$WORKDIR:/work-dir:rw,exec" \
           rebuilding-the-wheel \
           "$@"
}

podman build --tag rebuilding-the-wheel -f ./Containerfile

in_container ./mirror-sdists.sh "$TOPLEVEL"
in_container ./install-from-mirror.sh "$TOPLEVEL"
