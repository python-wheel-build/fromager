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

pip install -U langchain

pip freeze

# List packages and versions ls -1 */WHEEL | sed 's%\(.*\)-\([0-9][0-9]*\)\.\([0-9][0-9]*\)\.\?\([0-9][0-9]*\)\?\.dist-info/WHEEL%\1==\2.\3.\4%' | sort -f

# List files in site-packages and filter
# Note - some packages are just a single file in site-packages
# Note - some packages list dirs in top_level.txt that differ (e.g. PyYaml has _yaml and yaml)
# ls -1 */WHEEL | sed 's%\(.*\)-\([0-9][0-9]*\)\.\([0-9][0-9]*\)\.\?\([0-9][0-9]*\)\?\.dist-info/WHEEL%\1%' | while read  d; do find $d -type f | grep -v '\(\.py\|__pycache__\)'

# Binary files
#find . -type f ! -size 0 -exec grep -IL . "{}" \; | grep -v '\.pyc'

# Infer binary from Tag
cd $SITE_PKGS_DIR && grep Tag */WHEEL | grep -v py3-none-any | sed 's%\(.*\)-\([0-9][0-9]*\)\.\([0-9][0-9]*\)\.\?\([0-9][0-9]*\)\?\.dist-info/WHEEL.*%\1%' | uniq

# Binary packages:
# PyYAML
# SQLAlchemy
# aiohttp
# charset_normalizer
# frozenlist
# greenlet
# jsonpatch
# jsonpointer
# multidict
# numpy
# orjson
# pydantic_core
# yarl

deactivate

