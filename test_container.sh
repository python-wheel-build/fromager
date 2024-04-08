#!/bin/bash

set -xe
set -o pipefail

# Create a separate work dir so we can save the output to compare to
# what we get when we run the same scripts outside of the container.
WORKDIR=$(pwd)/work-dir-container
export WORKDIR
mkdir -p $WORKDIR

PYTHON=${PYTHON:-python3}

logfile="$WORKDIR/test-container-${PYTHON}.log"
exec > >(tee "$logfile") 2>&1

podman build --tag rebuilding-the-wheel -f ./Containerfile

in_container() {
    podman run -it --rm \
           -e PYTHON=$PYTHON \
           -e WORKDIR=/work-dir \
           -e VERBOSE=true \
           --userns=keep-id \
           --security-opt label=disable \
           --volume .:/src:rw,exec \
           --volume $WORKDIR:/work-dir:rw,exec \
           rebuilding-the-wheel \
           "$@"
}

in_container ./mirror-sdists.sh
in_container ./install-from-mirror.sh
