#!/bin/bash

set -e -o pipefail

# Look for individual packages, but not the dev tool groups.
grep '^RUN dnf -y install' Containerfile | sed 's/RUN /sudo /g' | sh -x
