#!/bin/bash

set -x

VENV=$(basename $(mktemp --dry-run --directory --tmpdir=. venvXXXX))
PYTHON=python3.9

delete_venv_on_exit() {
  rm -rf $VENV/
}
trap delete_venv_on_exit EXIT

setup() {
  $PYTHON -m venv $VENV
  . ./$VENV/bin/activate
  pip install -U pip
  export SITE_PKGS_DIR=$VENV/lib/$PYTHON/site-packages
}

setup

pip install -U python-pypi-mirror

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

# pypi-mirror download -d downloads/ langchain

rm -rf downloads/ simple/
pypi-mirror download -d downloads/ aiohttp setuptools wheel hatch-fancy-pypi-readme 'flit_core<4,>=3.8' 'setuptools-scm[toml]' pluggy hatchling expandvars calver hatch-vcs cython
pypi-mirror create -d downloads/ -m simple/

deactivate
