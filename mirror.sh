#!/bin/bash

set -x

VENV=$(basename $(mktemp --dry-run --directory --tmpdir=. venvXXXX))
PYTHON=python3.9
BUILD_REQUIRES=

delete_venv_on_exit() {
  [ $BUILD_REQUIRES ] && rm -f $BUILD_REQUIRES
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

# pypi-mirror download -d downloads/ langchain
#pypi-mirror download -d downloads/ aiohttp setuptools wheel hatch-fancy-pypi-readme 'flit_core<4,>=3.8' 'setuptools-scm[toml]' pluggy hatchling expandvars calver hatch-vcs cython

rm -rf downloads/ simple/
pypi-mirror download -d downloads/ aiohttp

BUILD_REQUIRES=$(mktemp --tmpdir=. build-requires-XXXX.txt)
for sdist in downloads/*.tar.gz; do
  tmp_unpack_dir=$(mktemp --tmpdir=. --directory tmpXXXX)
  tar -C $tmp_unpack_dir -xvzf $sdist

  pyproject_toml=$(ls -1 $tmp_unpack_dir/*/pyproject.toml)

  tmp_build_requires=$(mktemp --tmpdir=. build-requires-XXXX.txt)
  $PYTHON extract-build-requires.py < $pyproject_toml >> $tmp_build_requires

  # Build backend hooks usually may build requires installed
  pip install -U -r $tmp_build_requires
  cat $tmp_build_requires >> $BUILD_REQUIRES
  rm -f $tmp_build_requires

  extract_script=$(pwd)/extract-build-requires.py

  (cd $(dirname $pyproject_toml) && $PYTHON $extract_script --backend < pyproject.toml) >> $BUILD_REQUIRES

  rm -rf $tmp_unpack_dir
done

pypi-mirror download -d downloads/ -r $BUILD_REQUIRES

pypi-mirror create -d downloads/ -m simple/

deactivate
