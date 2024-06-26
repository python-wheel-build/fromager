#!/bin/bash

# Run all of the e2e tests. Useful for local development.

set -e
set -o pipefail

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

for test_script in $SCRIPTDIR/test_*.sh; do
    echo "****************************************"
    echo "$test_script"
    echo "****************************************"
    $test_script
done
