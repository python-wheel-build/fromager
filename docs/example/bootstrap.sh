#!/bin/bash

# Script for manually testing the bootstrap process using a container
catch() {
if [ ! -f "$CONSTRAINTS" ] && [ -f "$CONSTRAINTS_FILE" ]; then
	rm -f "$CONSTRAINTS_FILE"
fi

if [ ! -f "$REQUIREMENTS" ] && [ -f "$REQUIREMENTS_FILE" ]; then
	rm -f "$REQUIREMENTS_FILE"
fi
}
trap 'catch' EXIT INT

usage() { echo "Usage: CONTAINERFILE CONSTRAINTS REQUIREMENTS" 1>&2; exit 1; }

if [ "$#" -lt 3 ]; then
   usage
fi

set -x
set -e
set -o pipefail

CONTAINERFILE="$1"
CONSTRAINTS="$2"
REQUIREMENTS="$3"

if [ ! -f "$CONSTRAINTS" ]; then
	CONSTRAINTS_FILE=$(mktemp)
	echo "$CONSTRAINTS"  | tr ',' '\n' > "$CONSTRAINTS_FILE"
else
	CONSTRAINTS_FILE="./$CONSTRAINTS"
fi

if [ ! -f "$REQUIREMENTS" ]; then
	REQUIREMENTS_FILE=$(mktemp)
	echo "$REQUIREMENTS"  | tr ',' '\n' > "$REQUIREMENTS_FILE"
else
	REQUIREMENTS_FILE="./$REQUIREMENTS"
fi

IMAGE="wheels-builder"
# Strip the dev suffix, if any
VARIANT="cpu-ubi9"

# Create the output directory so we can mount it when we run the
# container.
OUTDIR=bootstrap-output
CCACHE_DIR=.bootstrap-ccache
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
       --volume "${CONSTRAINTS_FILE}:/bootstrap-inputs/constraints.txt" \
       --volume "${REQUIREMENTS_FILE}:/bootstrap-inputs/requirements.txt" \
       "$IMAGE" \
       \
       fromager \
       --constraints-file "/bootstrap-inputs/constraints.txt" \
       --log-file="$OUTDIR/bootstrap.log" \
       --sdists-repo="$OUTDIR/sdists-repo" \
       --wheels-repo="$OUTDIR/wheels-repo" \
       --work-dir="$OUTDIR/work-dir" \
       bootstrap -r "/bootstrap-inputs/requirements.txt"
