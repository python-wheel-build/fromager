#!/bin/bash

VENV=$(basename $(mktemp --dry-run --directory --tmpdir=. venvXXXX))
PYTHON=python3.9

delete_venv_on_exit() {
  rm -rf $VENV/
}
trap delete_venv_on_exit EXIT

setup() {
  $PYTHON -m venv $VENV
  . ./$VENV/bin/activate
  export SITE_PKGS_DIR=$VENV/lib/$PYTHON/site-packages
}

pip install -U python-pypi-mirror

pypi-mirror download -d downloads/ langchain
pypi-mirror create -d downloads/ -m simple

deactivate
