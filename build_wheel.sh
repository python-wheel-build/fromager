#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck disable=SC1091
source "$SCRIPTDIR/common.sh"

usage() {
  local err="$1"
  if [ -n "$err" ]; then
    echo "ERROR: $err"
    echo
  fi
  cat - <<EOF
build_wheel.sh [-h]
build_wheel.sh [-i] DIST VERSION [artifacts-dir]

  DIST            The name of the distribution to build.

  VERSION         The version of DIST to build.

  ARTIFACTS-DIR   Where to put the build artifacts. Defaults to "artifacts".

  -i              Use build isolation, running everything in containers.

  -h              This help message.
EOF
}

DO_SHIFT=false
BUILDER=build_wheel
while getopts "ih" opt; do
  case "$opt" in
    i)
      BUILDER=build_wheel_isolated
      DO_SHIFT=true
      ;;
    h)
      usage
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

if "$DO_SHIFT"; then
  shift
fi

DIST="$1"
VERSION="$2"
ARTIFACTS_DIR="${3:-artifacts}"

if [ -z "$DIST" ]; then
  usage "Specify a DIST to build"
  exit 1
fi
if [ -z "$VERSION" ]; then
  usage "Specify the version of $DIST to build"
  exit 1
fi

build_wheel_isolated() {
  local dist="$1"; shift
  local version="$1"; shift
  local artifacts_dir="$1"; shift

  # Build the base image.
  podman build \
         --tag e2e-build-base \
         -f "$SCRIPTDIR/Containerfile.e2e" \
         --build-arg="PYTHON=$PYTHON"

  # Create an image for building the wheel
  podman build -f "$SCRIPTDIR/Containerfile.e2e-one-wheel" \
         --tag "e2e-build-$dist" \
         --build-arg="DIST=$dist" \
         --build-arg="VERSION=$version" \
         --build-arg="WHEEL_SERVER_URL=$WHEEL_SERVER_URL" \
         --build-arg="SDIST_SERVER_URL=$SDIST_SERVER_URL"

  # Run the image to build the wheel.
  podman run -it \
         --name="e2e-build-$dist" \
         --replace \
         --network=none \
         --security-opt label=disable \
         -e "WHEEL_SERVER_URL=${WHEEL_SERVER_URL}" \
         "e2e-build-$dist"

  # Copy the results of the build out of the container, then clean up.
  mkdir -p "${artifacts_dir}"
  podman cp "e2e-build-$dist:/work-dir/built-artifacts.tar" "$artifacts_dir"
  podman rm "e2e-build-$dist"
  podman image rm "e2e-build-$dist"
}

build_wheel() {
  local dist="$1"; shift
  local version="$1"; shift
  local artifacts_dir="$1"; shift

  mkdir -p sdists-repo
  mkdir -p "${WORKDIR}"
  mkdir -p build-logs

  VENV="${WORKDIR}/venv-build-wheel"
  install_tools "$VENV"

  # Download the source archive
  python3 -m mirror_builder \
          --log-file build-logs/download-source-archive.log \
          --work-dir "$WORKDIR" \
          --sdists-repo sdists-repo \
          --wheels-repo wheels-repo \
          download-source-archive "${DIST}" "${VERSION}" "$SDIST_SERVER_URL"

  # Prepare the source dir for building
  python3 -m mirror_builder \
          --log-file build-logs/prepare-source.log \
          --work-dir "$WORKDIR" \
          --sdists-repo sdists-repo \
          --wheels-repo wheels-repo \
          prepare-source "${DIST}" "${VERSION}"

  # Prepare the build environment
  python3 -m mirror_builder \
          --log-file build-logs/prepare-build.log \
          --work-dir "$WORKDIR" \
          --sdists-repo sdists-repo \
          --wheels-repo wheels-repo \
          --wheel-server-url "${WHEEL_SERVER_URL}" \
          prepare-build "${DIST}" "${VERSION}"

  # Build the wheel.
  python3 -m mirror_builder \
          --log-file build-logs/build.log \
          --wheel-server-url "$WHEEL_SERVER_URL" \
          --work-dir "$WORKDIR" \
          --sdists-repo sdists-repo \
          --wheels-repo wheels-repo \
          build "$DIST" "$VERSION"

  # Copy the results of the build to the artifacts directory in a
  # tarball as is done when extracting content from the container
  # build for isolated builds.
  mkdir -p "${artifacts_dir}"
  tar cvf "$artifacts_dir/built-artifacts.tar" wheels-repo/build sdists-repo/downloads build-logs work-dir/*/*requirements.txt
}

"$BUILDER" "${DIST}" "${VERSION}" "${ARTIFACTS_DIR}"
