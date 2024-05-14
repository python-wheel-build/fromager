#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TOPDIR="$( cd "${SCRIPTDIR}/.." && pwd )"
# shellcheck disable=SC1091
source "$TOPDIR/common.sh"

outside_of_container() {
    mkdir -p "$WORKDIR"
    mkdir -p sdists-repo
    mkdir -p wheels-repo
    mkdir -p build-logs

    # Redirect stdout/stderr to logfile
    logfile="$WORKDIR/build-cuda.log"
    exec > >(tee "$logfile") 2>&1

    image_tag="cuda-ubi9-builder"

    podman build \
           --tag "$image_tag" \
           -f "$SCRIPTDIR/Containerfile.cuda-ubi9" \
           --build-arg="TOOL_SERVER_URL=$TOOL_SERVER_URL" \
           --build-arg="WHEEL_SERVER_URL=$WHEEL_SERVER_URL" \
           --build-arg="SDIST_SERVER_URL=$SDIST_SERVER_URL" \
           .

    # Run the image to build the wheel.
    podman run -it \
           --name="$image_tag" \
           --replace \
           --security-opt label=disable \
           -e "BUILD_ORDER_FILE=$BUILD_ORDER_FILE" \
           --volume .:/src:rw,exec \
           "$image_tag"
}

inside_of_container() {
    jq -r '.[] | select(.prebuilt == false) | .dist + " " + .version' "$BUILD_ORDER_FILE" \
      | while read -r dist version; do
      ./build_wheel.sh -d "$dist" -v "$version" -V cuda
    done

    # Show what all the binary wheels linked to. Using auditwheel on
    # something that is pure python produces an error, so look for
    # packages with the arch in them so we only get binary wheels.
    # shellcheck disable=SC2231
    for wheel in wheels-repo/downloads/*$(uname -m)*.whl; do
        auditwheel show "$wheel" || true
    done
}

IN_CONTAINER=${IN_CONTAINER:-false}
if [ -n "$1" ]; then
   BUILD_ORDER_FILE="$1"
else
    BUILD_ORDER_FILE="${BUILD_ORDER_FILE:-llama-cpp-build-order.json}"
fi

if "${IN_CONTAINER}"; then
    inside_of_container
else
    outside_of_container
fi
