#!/bin/bash

set -xe
set -o pipefail
export PS4='+ ${BASH_SOURCE#$HOME/}:$LINENO \011'

WORKDIR=$(realpath $(pwd)/work-dir)
if [ -d $WORKDIR ]; then
    echo "Clean up $WORKDIR first"
    exit 1
fi
mkdir -p $WORKDIR

# Redirect stdout/stderr to logfile
logfile="$WORKDIR/mirror-sdists.log"
exec > >(tee "$logfile") 2>&1

TOPLEVEL="${1:-langchain}"

VENV=$WORKDIR/venv
PYTHON=python3.9

SDISTS_REPO=$(realpath $(pwd)/sdists-repo)

setup() {
  if [ ! -d $VENV ]; then
    $PYTHON -m venv $VENV
  fi
  . $VENV/bin/activate
  pip install -U pip
  # Dependencies for the mirror building scripts
  pip install -U \
      python-pypi-mirror \
      toml \
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
  jq --argjson obj "{\"type\":\"${type}\",\"req\":\"${req//\"/\'}\",\"why\":\"${why}\"}" '. += [$obj]' ${SDISTS_REPO}/build-order.json > tmp.$$.json && mv tmp.$$.json ${SDISTS_REPO}/build-order.json
}
}

download_sdist() {
  local req="$1"; shift
  python3 ./resolve_and_download.py --dest ${SDISTS_REPO}/downloads/ "${req}"
}

get_downloaded_sdist() {
    local input=$1
    grep Saved $input | cut -d ' ' -f 2-
}

collect_build_requires() {
  local sdist="$1"; shift
  local why="$1"; shift

  local next_why=$(basename ${sdist} .tar.gz)

  local unpack_dir=${WORKDIR}/$(basename ${sdist} .tar.gz)
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
  (cd ${extract_dir} && $PYTHON $extract_script --build-system) | tee "${build_system_deps}"

  cat "${build_system_deps}" | while read -r req_iter; do
      download_output=${WORKDIR}/download-$(${parse_script} "${req_iter}").log
      download_sdist "${req_iter}" | tee $download_output
      local req_sdist=$(get_downloaded_sdist $download_output)
      if [ -n "${req_sdist}" ]; then
        collect_build_requires "${req_sdist}" "${why} -> ${next_why}"

        add_to_build_order "build_system" "${req_iter}" "${why}"

        # We may need these dependencies installed in order to run build hooks
        # Example: frozenlist build-system.requires includes expandvars because
        # it is used by the packaging/pep517_backend/ build backend
        pip install -U "${req_iter}"
      fi
  done

  echo "Build backend dependencies for ${sdist}:"
  (cd ${extract_dir} && $PYTHON $extract_script --build-backend) | tee "${build_backend_deps}"

  cat "${build_backend_deps}" | while read -r req_iter; do
    download_output=${WORKDIR}/download-$(${parse_script} "${req_iter}").log
    download_sdist "${req_iter}" | tee $download_output
    local req_sdist=$(get_downloaded_sdist $download_output)
    if [ -n "${req_sdist}" ]; then
      collect_build_requires "${req_sdist}" "${why} -> ${next_why}"

      add_to_build_order "build_backend" "${req_iter}" "${why}"

      # Build backends are often used to package themselves, so in
      # order to determine their dependencies they may need to be
      # installed.
      pip install -U "${req_iter}"
    fi
  done

  echo "Regular dependencies for ${sdist}:"
  (cd ${extract_dir} && $PYTHON $extract_script) | tee "${normal_deps}"

  cat "${normal_deps}" | while read -r req_iter; do
    download_output=${WORKDIR}/download-$(${parse_script} "${req_iter}").log
    download_sdist "${req_iter}" | tee $download_output
    local req_sdist=$(get_downloaded_sdist $download_output)
    if [ -n "${req_sdist}" ]; then
      collect_build_requires "${req_sdist}" "${why} -> ${next_why}"

      add_to_build_order "dependency" "${req_iter}" "${why}"
    fi
  done
}

setup

rm -rf ${SDISTS_REPO}/; mkdir -p ${SDISTS_REPO}/downloads/
echo -n "[]" > ${SDISTS_REPO}/build-order.json

rm -rf "${WHEELS_REPO}"
mkdir -p "${WHEELS_REPO}/downloads"

download_sdist "${TOPLEVEL}" | tee $WORKDIR/toplevel-download.log
collect_build_requires $(get_downloaded_sdist $WORKDIR/toplevel-download.log) ""

add_to_build_order "toplevel" "${TOPLEVEL}" ""

pypi-mirror create -d ${SDISTS_REPO}/downloads/ -m ${SDISTS_REPO}/simple/

deactivate
