#!/bin/bash

set -xe
set -o pipefail

WORKDIR=$(realpath $(pwd)/work-dir)
mkdir -p $WORKDIR

logfile="$WORKDIR/test-container.log"
exec > >(tee "$logfile") 2>&1

podman build --tag rebuilding-the-wheel -f ./Containerfile

# Create a separate work dir so we can save the output to compare to
# what we get when we run the same scripts outside of the container.
mkdir -p container-work-dir
chmod ugo+rwx container-work-dir

podman run -it --rm \
       -e PYTHON_TO_TEST=python3.12 \
       -e WORKDIR=/src/container-work-dir \
       --userns=keep-id \
       --security-opt label=disable \
       --volume .:/src:rw,exec \
       rebuilding-the-wheel \
       ./test.sh "$@"
