#!/bin/bash

# We ignore the warning about unreachable code because some of the
# test scripts generate scripts at runtime that use code defined in
# functions, and in the linter it looks like those functions are not
# being run anywhere.
UNREACHABLE=SC2317

# shellcheck disable=SC2046
shellcheck --exclude="$UNREACHABLE" --external-sources --format=gcc $(git ls-files '*.sh')
