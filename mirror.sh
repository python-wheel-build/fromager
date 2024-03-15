#!/bin/bash

set -xe

VENV=$(basename $(mktemp --dry-run --directory --tmpdir=. venvXXXX))
PYTHON=python3.9
BUILD_REQUIRES=
ret_BUILD_REQUIRES=
tmp_unpack_dir=

on_exit() {
  [ $BUILD_REQUIRES ] && rm -f $BUILD_REQUIRES
  [ $ret_BUILD_REQUIRES ] && rm -f $ret_BUILD_REQUIRES
  [ $tmp_unpack_dir ] && rm -rf $tmp_unpack_dir
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

rm -rf downloads/ simple/
pypi-mirror download -d downloads/ langchain

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

collect_build_requires() {
  ret_BUILD_REQUIRES=$(mktemp --tmpdir=. build-requires-XXXX.txt)
  for sdist in downloads/*.tar.gz; do
    tmp_unpack_dir=$(mktemp --tmpdir=. --directory tmpXXXX)
    tar -C $tmp_unpack_dir -xvzf $sdist

    if [ ! -e $tmp_unpack_dir/*/pyproject.toml ]; then
      rm -rf $tmp_unpack_dir; tmp_unpack_dir=
      continue
    fi

    pyproject_toml=$(ls -1 $tmp_unpack_dir/*/pyproject.toml)

    tmp_build_requires=$(mktemp --tmpdir=. build-requires-XXXX.txt)
    $PYTHON extract-build-requires.py < $pyproject_toml >> $tmp_build_requires

    # Build backend hooks usually may build requires installed
    pip install -U -r $tmp_build_requires
    cat $tmp_build_requires >> $ret_BUILD_REQUIRES
    rm -f $tmp_build_requires

    extract_script=$(pwd)/extract-build-requires.py

    (cd $(dirname $pyproject_toml) && $PYTHON $extract_script --backend < pyproject.toml) >> $ret_BUILD_REQUIRES

    rm -rf $tmp_unpack_dir; tmp_unpack_dir=
  done
  [ $BUILD_REQUIRES ] && rm -f $BUILD_REQUIRES
  BUILD_REQUIRES=$ret_BUILD_REQUIRES; ret_BUILD_REQUIRES=
}

collect_build_requires
while true; do
  pypi-mirror download -d downloads/ -r $BUILD_REQUIRES

  # Ugh, keep downloading build requirements until we're not collecting new ones
  BUILD_REQUIRES_LEN=$(wc -l < $BUILD_REQUIRES)
  collect_build_requires
  new_BUILD_REQUIRES_LEN=$(wc -l < $BUILD_REQUIRES)
  [ $BUILD_REQUIRES_LEN -eq $new_BUILD_REQUIRES_LEN ] && break
done

pypi-mirror create -d downloads/ -m simple/

deactivate
