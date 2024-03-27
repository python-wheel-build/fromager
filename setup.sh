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

sudo dnf install -y python3 python3-devel rust cargo cmake autoconf automake

# Needed for cffi build
sudo dnf install -y libffi libffi-devel

# Needed for cryptography build
sudo dnf install -y openssl-devel

# Needed for pillow build
sudo dnf install -y zlib-devel libjpeg-devel

# Needed for 3.12 builds (on CentOS Stream 9)
sudo dnf install -y python3.12-devel
