#!/bin/bash

set -xe

# Python versions for testing
brew install python@3.9 python@3.12

# Needed for setuptools-rust and maturin build
# (cargo is part of the rust package)
brew install rust

# Needed for cffi build
brew install libffi

# Needed for cryptography build
brew install openssl

# Needed for pillow build
brew install zlib libjpeg