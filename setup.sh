#!/bin/bash

set -e -o pipefail

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

sudo dnf install python3 python3-devel rust cargo cmake autoconf automake
