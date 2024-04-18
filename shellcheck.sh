#!/bin/bash

shellcheck --external-sources --format=gcc $(git ls-files '*.sh')
