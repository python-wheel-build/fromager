#!/bin/bash

set -xe

# Redirect stdout/stderr to logfile
logfile=".mirror_$(date '+%Y-%m-%d_%H-%M-%S').log"
exec > >(tee "$logfile") 2>&1

TOPLEVEL="hatchling"
#TOPLEVEL="frozenlist"
#TOPLEVEL="langchain"

VENV=$(basename $(mktemp --dry-run --directory --tmpdir=. venvXXXX))
PYTHON=python3.9

on_exit() {
  rm -rf $VENV/
}
trap on_exit EXIT

setup() {
  $PYTHON -m venv $VENV
  . ./$VENV/bin/activate
  pip install -U pip
}

setup

pip install -U python-pypi-mirror toml pyproject_hooks

# cmake needed, otherwise:
# Building wheels for collected packages: patchelf, ninja
# ...
# Building wheel for patchelf (pyproject.toml) did not run successfully.
# ...
# Problem with the CMake installation, aborting build. CMake executable is cmake

# autoconf/automake needed, otherwise e.g.:
# [ 44%] Performing patch step for 'build_patchelf'
# ./bootstrap.sh: line 2: autoreconf: command not found

# rust/cargo needed, otherwise:
# Building wheels for collected packages: maturin
# error: can't find Rust compiler

# $ sudo dnf install cmake autoconf automake rust cargo

add_to_build_order() {
  local type="$1"; shift
  local req="$1"; shift
  jq --argjson obj "{\"type\":\"${type}\",\"req\":\"${req//\"/\'}\"}" '. += [$obj]' build-order.json > tmp.$$.json && mv tmp.$$.json build-order.json
}

download_sdist() {
  local req="$1"; shift
  pip download --dest downloads/ --no-deps --no-binary :all: "${req}" | grep Saved | cut -d ' ' -f 2-
  # FIXME: we should do better than returning zero and empty output if this (common case) happens:
  # Collecting flit_core>=3.3
  #   File was already downloaded <...>
  #   Getting requirements to build wheel ... done
  #   Preparing metadata (pyproject.toml) ... done
  # Successfully downloaded flit_core
}

collect_build_requires() {
  local sdist="$1"; shift

  local tmp_unpack_dir=$(mktemp --tmpdir=. --directory tmpXXXX)
  tar -C $tmp_unpack_dir -xvzf $sdist

  if [ -e $tmp_unpack_dir/*/pyproject.toml ]; then
    local pyproject_toml=$(ls -1 $tmp_unpack_dir/*/pyproject.toml)
    local extract_script=$(pwd)/extract-build-requires.py

    (cd $(dirname $pyproject_toml) && $PYTHON $extract_script < pyproject.toml) | while read -r req_iter; do
      local req_sdist=$(download_sdist "${req_iter}")
      if [ -n "${req_sdist}" ]; then
        collect_build_requires "${req_sdist}"

        add_to_build_order "build_system" "${req_iter}"

        # Build backend hooks usually may build requires installed
        pip install -U "${req_iter}"
      fi
    done

    (cd $(dirname $pyproject_toml) && $PYTHON $extract_script --backend < pyproject.toml) | while read -r req_iter; do
      local req_sdist=$(download_sdist "${req_iter}")
      if [ -n "${req_sdist}" ]; then
        collect_build_requires "${req_sdist}"

        add_to_build_order "backend_build_wheel" "${req_iter}"
      fi
    done
  fi

  rm -rf $tmp_unpack_dir
}

rm -rf downloads/ simple/

echo -n "[]" > build-order.json

collect_build_requires $(download_sdist "${TOPLEVEL}")

add_to_build_order "toplevel" "${TOPLEVEL}"

pypi-mirror create -d downloads/ -m simple/

deactivate
