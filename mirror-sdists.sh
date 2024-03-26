#!/bin/bash

set -xe
set -o pipefail
export PS4='+ ${BASH_SOURCE#$HOME/}:$LINENO \011'

WORKDIR=$(realpath $(pwd)/work-dir)
mkdir -p $WORKDIR

PYTHON=${PYTHON:-python3.9}
PYTHON_VERSION=$($PYTHON --version | cut -f2 -d' ')

# Redirect stdout/stderr to logfile
logfile="$WORKDIR/mirror-sdists-${PYTHON_VERSION}.log"
exec > >(tee "$logfile") 2>&1

TOPLEVEL="${1:-langchain}"

VENV=$WORKDIR/venv-${PYTHON_VERSION}

WHEELS_REPO=$(realpath $(pwd)/wheels-repo)
SDISTS_REPO=$(realpath $(pwd)/sdists-repo)
BUILD_ORDER=${SDISTS_REPO}/build-order-${PYTHON_VERSION}.json

setup() {
  if [ ! -d $VENV ]; then
    $PYTHON -m venv $VENV
  fi
  . $VENV/bin/activate
  pip install -U pip
  # Dependencies for the mirror building scripts
  pip install -U \
      python-pypi-mirror \
      tomli \
      pyproject_hooks \
      packaging \
      wheel \
      build \
      resolvelib \
      html5lib \
      requests \
      packaging
}

already_processed() {
  local req="$1"

  jq .[].req < "${BUILD_ORDER}" | grep "$req"
}

add_to_build_order() {
  local type="$1"; shift
  local req="$1"; shift
  local why="$1"; shift
  jq --argjson obj "{\"type\":\"${type}\",\"req\":\"${req//\"/\'}\",\"why\":\"${why}\"}" '. += [$obj]' ${BUILD_ORDER} > tmp.$$.json && mv tmp.$$.json ${BUILD_ORDER}
}

update_mirror() {
  pypi-mirror create -d "${WHEELS_REPO}/downloads" -m "${WHEELS_REPO}/simple"
}

build_wheel() {
  local sdist_dir="$1"; shift
  local dest_dir="$1"; shift

  (cd "${sdist_dir}" && python -m build --wheel . && mv dist/*.whl "${WHEELS_REPO}/downloads/")
  update_mirror
}

download_sdist() {
  local req="$1"; shift
  python3 ./resolve_and_download.py --dest ${SDISTS_REPO}/downloads/ "${req}"
}

get_downloaded_sdist() {
    local input=$1
    grep -E '(Existing|Saved)' $input | cut -d ' ' -f 2-
}

safe_install() {
    local req="$1"; shift

    pip -vvv install \
        --upgrade \
        --disable-pip-version-check \
        --only-binary :all: \
        --index-url "${WHEEL_SERVER_URL}" \
        "${req}"
}

collect_build_requires() {
  local req="$1"; shift
  local sdist="$1"; shift
  local why="$1"; shift

  # Check if we have already processed this requirement to avoid cycles.
  if already_processed "$req"; then
      echo "$req has already been seen"
      return
  fi

  local next_why=$(basename ${sdist} .tar.gz)

  local unpack_dir=${WORKDIR}/$(basename ${sdist} .tar.gz)
  # If the sdist was already unpacked we may have been doing the
  # analysis with a different Python version, so remove the directory
  # to ensure we get clean results this time.
  rm -rf "${unpack_dir}"
  mkdir -p "${unpack_dir}"
  tar -C $unpack_dir -xvzf $sdist
  # We can't always predict what case will be used in the directory
  # name or whether it will match the prefix of the downloaded sdist.
  local extract_dir="$(ls -1d ${unpack_dir}/*)"

  local extract_script=$(pwd)/extract-requires.py
  local parse_script=$(pwd)/parse_dep.py
  local build_system_deps="${unpack_dir}/build-system-requirements.txt"
  local build_backend_deps="${unpack_dir}/build-backend-requirements.txt"
  local normal_deps="${unpack_dir}/requirements.txt"

  echo "Build system dependencies for ${sdist}:"
  (cd ${extract_dir} && $PYTHON $extract_script --build-system "${req}") | tee "${build_system_deps}"

  cat "${build_system_deps}" | while read -r req_iter; do

      # Check if we have already processed this requirement to avoid
      # cycles. Do this before recursing to avoid adding an item to the
      # build order list multiple times.
      if already_processed "$req_iter"; then
          echo "$req_iter has already been seen"
          continue
      fi

      download_output=${WORKDIR}/download-$(${parse_script} "${req_iter}").log
      download_sdist "${req_iter}" | tee $download_output
      local req_sdist=$(get_downloaded_sdist $download_output)
      if [ -n "${req_sdist}" ]; then
        collect_build_requires "${req_iter}" "${req_sdist}" "${why} -> ${next_why}"

        add_to_build_order "build_system" "${req_iter}" "${why}"
      fi

      # We may need these dependencies installed in order to run build hooks
      # Example: frozenlist build-system.requires includes expandvars because
      # it is used by the packaging/pep517_backend/ build backend
      safe_install "${req_iter}"
  done

  echo "Build backend dependencies for ${sdist}:"
  (cd ${extract_dir} && $PYTHON $extract_script --build-backend "${req}") | tee "${build_backend_deps}"

  cat "${build_backend_deps}" | while read -r req_iter; do

    # Check if we have already processed this requirement to avoid
    # cycles. Do this before recursing to avoid adding an item to the
    # build order list multiple times.
    if already_processed "$req_iter"; then
        echo "$req_iter has already been seen"
        continue
    fi

    download_output=${WORKDIR}/download-$(${parse_script} "${req_iter}").log
    download_sdist "${req_iter}" | tee $download_output
    local req_sdist=$(get_downloaded_sdist $download_output)
    if [ -n "${req_sdist}" ]; then
      collect_build_requires "${req_iter}" "${req_sdist}" "${why} -> ${next_why}"

      add_to_build_order "build_backend" "${req_iter}" "${why}"
    fi

    # Build backends are often used to package themselves, so in
    # order to determine their dependencies they may need to be
    # installed.
    safe_install "${req_iter}"
  done

  # Build the wheel for this package after handling all of the
  # build-related dependencies.
  build_wheel "${extract_dir}" "${WHEELS_REPO}/downloads"

  echo "Regular dependencies for ${sdist}:"
  (cd ${extract_dir} && $PYTHON $extract_script "${req}") | tee "${normal_deps}"

  cat "${normal_deps}" | while read -r req_iter; do

    # Check if we have already processed this requirement to avoid
    # cycles. Do this before recursing to avoid adding an item to the
    # build order list multiple times.
    if already_processed "$req_iter"; then
        echo "$req_iter has already been seen"
        continue
    fi

    download_output=${WORKDIR}/download-$(${parse_script} "${req_iter}").log
    download_sdist "${req_iter}" | tee $download_output
    local req_sdist=$(get_downloaded_sdist $download_output)
    if [ -n "${req_sdist}" ]; then
      collect_build_requires "${req_iter}" "${req_sdist}" "${why} -> ${next_why}"

      add_to_build_order "dependency" "${req_iter}" "${why}"
    fi
  done
}

stop_wheel_server() {
    kill ${HTTP_SERVER_PID}
}
start_wheel_server() {
    update_mirror
    $PYTHON -m http.server --directory "${WHEELS_REPO}" 9090 &
    HTTP_SERVER_PID=$!
    WHEEL_SERVER_URL="http://localhost:9090/simple"
}

on_exit() {
    stop_wheel_server
}
trap on_exit EXIT SIGINT SIGTERM

setup

mkdir -p ${SDISTS_REPO}/downloads/
echo -n "[]" > ${BUILD_ORDER}

mkdir -p "${WHEELS_REPO}/downloads"
start_wheel_server

download_sdist "${TOPLEVEL}" | tee $WORKDIR/toplevel-download.log
collect_build_requires "${TOPLEVEL}" $(get_downloaded_sdist $WORKDIR/toplevel-download.log) ""

add_to_build_order "toplevel" "${TOPLEVEL}" ""

pypi-mirror create -d ${SDISTS_REPO}/downloads/ -m ${SDISTS_REPO}/simple/

deactivate
