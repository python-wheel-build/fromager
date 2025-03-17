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

usage() {
	echo "Usage: [-f <fromager arguments> | -k <seconds>] CONTAINERFILE CONSTRAINTS REQUIREMENTS"
	echo "       -c: Execute different command in container (must be passed with double quotes)"
	echo "       -f: additional fromager arguments"
	echo "       -h: help (this message)"
	echo "       -k: set number of seconds to keep container running after execution"
}

COMMAND=""
FROMAGER_ARGS=""
KEEPALIVE=0

BASE_ARGS=()
while [[ $# -gt 0 ]]; do
	case $1 in
	-h)
		usage
		exit 0
		;;
	-c)
		COMMAND="$2"
		shift
		shift
		;;
	-f)
		FROMAGER_ARGS="$2"
		shift
		shift
		;;
	-k)
		KEEPALIVE="$2"
		re='^[0-9]+$'
		if ! [[ "$KEEPALIVE" =~ $re ]]; then
			echo "-k value must be a number of seconds to keep container running"
			exit 1
		fi
		shift
		shift
		;;
	*)
	BASE_ARGS+=("$1")
	shift
	;;
	esac
done

# reset the args with base arguments
set -- "${BASE_ARGS[@]}"

if [ "$#" -lt 3 ]; then
   usage
   exit 1
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

# set the default command
[ -z "$COMMAND" ] && COMMAND="fromager ${FROMAGER_ARGS} \
       --constraints-file /bootstrap-inputs/constraints.txt \
       --log-file=$OUTDIR/bootstrap.log \
       --sdists-repo=$OUTDIR/sdists-repo \
       --wheels-repo=$OUTDIR/wheels-repo \
       --work-dir=$OUTDIR/work-dir \
       bootstrap -r /bootstrap-inputs/requirements.txt"

# Run fromager in the image to bootstrap the requirements file.
podman run \
       -it \
       --rm \
       --security-opt label=disable \
       --volume "./$OUTDIR:/work/bootstrap-output:rw,exec" \
       --volume "./$CCACHE_DIR:/var/cache/ccache:rw,exec" \
       --volume "${CONSTRAINTS_FILE}:/bootstrap-inputs/constraints.txt" \
       --volume "${REQUIREMENTS_FILE}:/bootstrap-inputs/requirements.txt" \
       --ulimit host \
       --pids-limit -1 \
       "$IMAGE" \
       sh -c "$COMMAND; sleep $KEEPALIVE"
