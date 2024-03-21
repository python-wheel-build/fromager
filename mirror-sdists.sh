#!/bin/bash

set -xe
set -o pipefail
export PS4='+ ${BASH_SOURCE#$HOME/}:$LINENO \011'

# Redirect stdout/stderr to logfile
logfile=".mirror_$(date '+%Y-%m-%d_%H-%M-%S').log"
exec > >(tee "$logfile") 2>&1

TMP=$(mktemp --tmpdir=. --directory tmpXXXX)

TOPLEVEL="${1:-langchain}"

VENV=$TMP/venv
PYTHON=python3.9

on_exit() {
  rm -rf $TMP/
}
trap on_exit EXIT SIGINT SIGTERM

setup() {
  if [ ! -d $VENV ]; then
    $PYTHON -m venv $VENV
  fi
  . ./$VENV/bin/activate
  pip install -U pip
}

setup

pip install -U python-pypi-mirror toml pyproject_hooks packaging wheel

add_to_build_order() {
  local type="$1"; shift
  local req="$1"; shift
  local why="$1"; shift
  jq --argjson obj "{\"type\":\"${type}\",\"req\":\"${req//\"/\'}\",\"why\":\"${why}\"}" '. += [$obj]' sdists-repo/build-order.json > tmp.$$.json && mv tmp.$$.json sdists-repo/build-order.json
}

download_sdist() {
  local req="$1"; shift
  pip download --dest sdists-repo/downloads/ --no-deps --no-binary :all: "${req}"
  # FIXME: we should do better than returning zero and empty output if this (common case) happens:
  # Collecting flit_core>=3.3
  #   File was already downloaded <...>
  #   Getting requirements to build wheel ... done
  #   Preparing metadata (pyproject.toml) ... done
  # Successfully downloaded flit_core
}

get_downloaded_sdist() {
    local input=$1
    grep Saved $input | cut -d ' ' -f 2-
}

collect_build_requires() {
  local sdist="$1"; shift
  local why="$1"; shift

  local next_why=$(basename ${sdist} .tar.gz)

  local tmp_unpack_dir=$(mktemp --tmpdir=$TMP --directory tmpXXXX)
  tar -C $tmp_unpack_dir -xvzf $sdist
  # We can't always predict what case will be used in the directory
  # name or whether it will match the prefix of the downloaded sdist.
  local extract_dir="$(ls -1d ${tmp_unpack_dir}/*)"

  local extract_script=$(pwd)/extract-requires.py
  local parse_script=$(pwd)/parse_dep.py
  local build_system_deps="${tmp_unpack_dir}/build-system-requirements.txt"
  local build_backend_deps="${tmp_unpack_dir}/build-backend-requirements.txt"
  local normal_deps="${tmp_unpack_dir}/requirements.txt"

  echo "Build system dependencies for ${sdist}:"
  (cd ${extract_dir} && $PYTHON $extract_script --build-system) | tee "${build_system_deps}"

  cat "${build_system_deps}" | while read -r req_iter; do
      download_output=${TMP}/download-$(${parse_script} "${req_iter}").log
      download_sdist "${req_iter}" | tee $download_output
      local req_sdist=$(get_downloaded_sdist $download_output)
      if [ -n "${req_sdist}" ]; then
        collect_build_requires "${req_sdist}" "${next_why}"

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
    download_output=${TMP}/download-$(${parse_script} "${req_iter}").log
    download_sdist "${req_iter}" | tee $download_output
    local req_sdist=$(get_downloaded_sdist $download_output)
    if [ -n "${req_sdist}" ]; then
      collect_build_requires "${req_sdist}" "${next_why}"

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
    download_output=${TMP}/download-$(${parse_script} "${req_iter}").log
    download_sdist "${req_iter}" | tee $download_output
    local req_sdist=$(get_downloaded_sdist $download_output)
    if [ -n "${req_sdist}" ]; then
      collect_build_requires "${req_sdist}" "${next_why}"

      add_to_build_order "dependency" "${req_iter}" "${why}"
    fi
  done
}

rm -rf sdists-repo/; mkdir sdists-repo/

echo -n "[]" > sdists-repo/build-order.json

download_sdist "${TOPLEVEL}" | tee $TMP/toplevel-download.log
collect_build_requires $(get_downloaded_sdist $TMP/toplevel-download.log) ""

add_to_build_order "toplevel" "${TOPLEVEL}" ""

pypi-mirror create -d sdists-repo/downloads/ -m sdists-repo/simple/

deactivate
