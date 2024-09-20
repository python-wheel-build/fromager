#!/bin/bash

# Script for manually testing the bootstrap process using a container

usage() { echo "Usage: CONSTRAINTS_FILE REQUIREMENTS_FILE" 1>&2; exit 1; }

if [ "$#" -ne 2 ]; then
   usage
fi

set -x
set -e
set -o pipefail

CONSTRAINTS_FILE="$1"
REQUIREMENTS_FILE="$2"

CONTAINERFILE="Containerfile"
IMAGE="wheels-builder"
# Strip the dev suffix, if any
VARIANT="cpu-ubi9"

# Create the output directory so we can mount it when we run the
# container.
OUTDIR=bootstrap-output
CCACHE_DIR=bootstrap-ccache
mkdir -p "$OUTDIR" "$CCACHE_DIR"

# Build the builder image
podman build \
       -f "$CONTAINERFILE" \
       -t "$IMAGE" \
       .

# Run fromager in the image to bootstrap the requirements file.
podman run \
       -it \
       --rm \
       --security-opt label=disable \
       --volume "./$OUTDIR:/work/bootstrap-output:rw,exec" \
       --volume "./$CCACHE_DIR:/var/cache/ccache:rw,exec" \
       --volume "./${CONSTRAINTS_FILE}:/bootstrap-inputs/constraints.txt" \
       --volume "./${REQUIREMENTS_FILE}:/bootstrap-inputs/requirements.txt" \
       "$IMAGE" \
       \
       fromager \
       --constraints-file "/bootstrap-inputs/constraints.txt" \
       --log-file="$OUTDIR/bootstrap.log" \
       --sdists-repo="$OUTDIR/sdists-repo" \
       --wheels-repo="$OUTDIR/wheels-repo" \
       --work-dir="$OUTDIR/work-dir" \
       bootstrap -r "/bootstrap-inputs/requirements.txt"
