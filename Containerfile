FROM fedora:39

# The base layer is minimal, so instead of tracking individual tools
# needed by different build steps or scripts we just install the
# development environment.
RUN dnf -y groupinstall "Development Tools" "Development Libraries"

# Redundant, but needed to ensure diff is present in CI.
# The diff command is needed in tests run while building patchelf
#
RUN dnf -y install diffutils

# Commands needed in test.sh
RUN dnf -y install procps-ng jq patch

# We use firejail to isolate wheel building processes from the internet
RUN dnf -y install firejail

# cmake needed, otherwise:
# Building wheels for collected packages: patchelf, ninja
# ...
# Building wheel for patchelf (pyproject.toml) did not run successfully.
# ...
# Problem with the CMake installation, aborting build. CMake executable is cmake
#
# autoconf/automake needed, otherwise e.g.:
# [ 44%] Performing patch step for 'build_patchelf'
# ./bootstrap.sh: line 2: autoreconf: command not found
RUN dnf -y install cmake autoconf automake

# C extension compilation
RUN dnf -y install  gcc g++

# Our ninja wheels wrap the ninja-build RPM package
RUN dnf -y install ninja-build

# rust/cargo needed, otherwise:
# Building wheels for collected packages: maturin
# error: can't find Rust compiler
RUN dnf -y install rust cargo

# Needed for cffi build
RUN dnf -y install libffi libffi-devel

# Needed for cryptography build
RUN dnf -y install openssl-devel

# Needed for pillow build
RUN dnf -y install zlib-devel libjpeg-devel

# Python dependencies (last in case we want to change versions)
# python3.12-devel needed for 3.12 builds (on CentOS Stream 9)
RUN dnf -y install python3.9 python3.11 python3.11-devel python3.12 python3.12-devel

WORKDIR /src
