#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

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
BUILD_TRACKER=${WORKDIR}/build-tracker-${PYTHON_VERSION}.json

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

add_to_build_order() {
  local type="$1"; shift
  local req="$1"; shift
  local why="$1"; shift
  jq --argjson obj "{\"type\":\"${type}\",\"req\":\"${req//\"/\'}\",\"why\":\"${why}\"}" '. += [$obj]' ${BUILD_ORDER} > tmp.$$.json && mv tmp.$$.json ${BUILD_ORDER}
}

add_to_build_tracker() {
  local resolved_name="$1"; shift
  jq --argjson obj "{\"name\":\"${resolved_name}\"}" '. += [$obj]' ${BUILD_TRACKER} > tmp.$$.json && mv tmp.$$.json ${BUILD_TRACKER}
}

already_built_or_in_process() {
  local resolved_name="$1"; shift
  jq -r '.[].name' < "${BUILD_TRACKER}" | grep "^${resolved_name}$"
}

update_mirror() {
  pypi-mirror create -d "${WHEELS_REPO}/downloads" -m "${WHEELS_REPO}/simple"
}

build_wheel() {
  local sdist_dir="$1"; shift
  local dest_dir="$1"; shift

  local -r unpack_dir=$(dirname "${sdist_dir}")
  local -r build_env="${unpack_dir}/build-env"
  $PYTHON -m venv "${build_env}"
  # FIXME: Still installs 'build' and 'wheel' from outside
  (cd "${sdist_dir}"\
       && source "${build_env}/bin/activate" \
       && pip install --disable-pip-version-check build wheel \
       && safe_install -r "${unpack_dir}/build-system-requirements.txt" \
       && safe_install -r "${unpack_dir}/build-backend-requirements.txt" \
       && pip freeze \
       && pwd \
       && python3 -m build \
                  --wheel \
                  --skip-dependency-check \
                  --no-isolation \
                  --outdir "${WHEELS_REPO}/downloads/" \
                  . \
      )
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
  pip -vvv install \
      --upgrade \
      --disable-pip-version-check \
      --only-binary :all: \
      --index-url "${WHEEL_SERVER_URL}" \
        "$@"
}

patch_sdist() {
  local extract_dir="$1"; shift

  for p in patches/$(basename "${extract_dir}")*.patch; do
    if [ -e "${p}" ]; then
      p=$(realpath "${p}")
      pushd "${extract_dir}"
      patch -p1 < "${p}"
      popd
    fi
  done
}

collect_build_requires() {
  local type="$1"; shift
  local req="$1"; shift
  local sdist="$1"; shift
  local why="$1"; shift

  local resolved_name=$(basename "${sdist}" .tar.gz)

  # Check if we have already processed this requirement to avoid cycles.
  if already_built_or_in_process "${resolved_name}"; then
      echo "${resolved_name} has already been seen"
      return
  fi
  add_to_build_tracker "${resolved_name}"

  local next_why="${why} -> ${resolved_name}"

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

  patch_sdist "${extract_dir}"

  local extract_script=$(pwd)/extract-requires.py
  local parse_script=$(pwd)/parse_dep.py
  local build_system_deps="${unpack_dir}/build-system-requirements.txt"
  local build_backend_deps="${unpack_dir}/build-backend-requirements.txt"
  local normal_deps="${unpack_dir}/requirements.txt"

  echo "Build system dependencies for ${resolved_name}:"
  (cd ${extract_dir} && $PYTHON $extract_script --build-system "${req}") | tee "${build_system_deps}"

  cat "${build_system_deps}" | while read -r req_iter; do
    download_output=${WORKDIR}/download-$(${parse_script} "${req_iter}").log
    download_sdist "${req_iter}" | tee $download_output
    local req_sdist=$(get_downloaded_sdist $download_output)
    if [ -n "${req_sdist}" ]; then
      collect_build_requires "build_system" "${req_iter}" "${req_sdist}" "${next_why}"
    fi

    # We may need these dependencies installed in order to run build hooks
    # Example: frozenlist build-system.requires includes expandvars because
    # it is used by the packaging/pep517_backend/ build backend
    safe_install "${req_iter}"
  done

  echo "Build backend dependencies for ${resolved_name}:"
  (cd ${extract_dir} && $PYTHON $extract_script --build-backend "${req}") | tee "${build_backend_deps}"

  cat "${build_backend_deps}" | while read -r req_iter; do
    download_output=${WORKDIR}/download-$(${parse_script} "${req_iter}").log
    download_sdist "${req_iter}" | tee $download_output
    local req_sdist=$(get_downloaded_sdist $download_output)
    if [ -n "${req_sdist}" ]; then
      collect_build_requires "build_backend" "${req_iter}" "${req_sdist}" "${next_why}"
    fi

    # Build backends are often used to package themselves, so in
    # order to determine their dependencies they may need to be
    # installed.
    safe_install "${req_iter}"
  done

  # Build the wheel for this package after handling all of the
  # build-related dependencies.
  build_wheel "${extract_dir}" "${WHEELS_REPO}/downloads"

  echo "Regular dependencies for ${resolved_name}:"
  (cd ${extract_dir} && $PYTHON $extract_script "${req}") | tee "${normal_deps}"

  cat "${normal_deps}" | while read -r req_iter; do
    download_output=${WORKDIR}/download-$(${parse_script} "${req_iter}").log
    download_sdist "${req_iter}" | tee $download_output
    local req_sdist=$(get_downloaded_sdist $download_output)
    if [ -n "${req_sdist}" ]; then
      collect_build_requires "dependency" "${req_iter}" "${req_sdist}" "${next_why}"
    fi
  done

  add_to_build_order "${type}" "${req}" "${why}"
}

handle_toplevel_requirement() {
  local req="$1"; shift

  local -r download_log="$WORKDIR/download-toplevel.log"
  download_sdist "${req}" | tee "${download_log}"
  local -r sdist="$(get_downloaded_sdist "${download_log}")"
  collect_build_requires "toplevel" "${req}" "${sdist}" ""
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
echo -n "[]" > ${BUILD_TRACKER}

mkdir -p "${WHEELS_REPO}/downloads"
start_wheel_server

handle_toplevel_requirement "${TOPLEVEL}"

pypi-mirror create -d ${SDISTS_REPO}/downloads/ -m ${SDISTS_REPO}/simple/

deactivate
