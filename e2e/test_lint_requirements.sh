#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# This script acts as an e2e test for lint_requirements command of fromager

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

pass=true

# Test to demonstrate that command works as expected when input files are valid

if ! fromager lint-requirements --resolve-requirements "$SCRIPTDIR/validate_inputs/constraints.txt" "$SCRIPTDIR/validate_inputs/requirements.txt"; then
    echo "the input files should have been recognized as correctly formatted" 1>&2
    pass=false
fi;

# Test to demonstrate failing of command due to missing input args

if fromager lint-requirements; then
    echo "missing input files should have been recognized by the command" 1>&2
    pass=false
fi;

# Test to demonstrate that command reports error for invalid / bad requirements

if fromager lint-requirements --resolve-requirements "$SCRIPTDIR/validate_inputs/constraints.txt" "$SCRIPTDIR/validate_inputs/invalid-requirements.txt"; then
    echo "invalid input files should have been recognized by the command" 1>&2
    pass=false
fi;

# Test to demonstrate that command reports error for invalid / bad constraints

if fromager lint-requirements --resolve-requirements "$SCRIPTDIR/validate_inputs/invalid-constraints.txt" "$SCRIPTDIR/validate_inputs/requirements.txt"; then
    echo "invalid input files should have been recognized by the command" 1>&2
    pass=false
fi;

# Test to demonstrate that command accepts duplicate entries in requirements files

if ! fromager lint-requirements --resolve-requirements "$SCRIPTDIR/validate_inputs/constraints.txt" "$SCRIPTDIR/validate_inputs/duplicate-requirements.txt"; then
    echo "duplicate entries in requirements files should have been recognized as valid" 1>&2
    pass=false
fi;

# Test to demonstrate that command accepts valid duplicate entries in constraint files

if ! fromager lint-requirements --resolve-requirements "$SCRIPTDIR/validate_inputs/valid-duplicate-constraints.txt" "$SCRIPTDIR/validate_inputs/requirements.txt"; then
    echo "the duplicate entries in files should have been recognized as valid" 1>&2
    pass=false
fi;

# Test to demonstrate that command rejects invalid duplicate entries in constraint files

if fromager lint-requirements --resolve-requirements "$SCRIPTDIR/validate_inputs/invalid-duplicate-constraints.txt" "$SCRIPTDIR/validate_inputs/requirements.txt"; then
    echo "duplicate entries in files should have been recognized by the command" 1>&2
    pass=false
fi;

$pass
