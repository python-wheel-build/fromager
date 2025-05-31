#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test that the fromager graph to-constraints command fails when given
# a graph with dependency conflicts.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

pass=true

# Test that the command fails when no input file is specified
if fromager graph to-constraints; then
    echo "Command should have failed when no input file is specified" 1>&2
    pass=false
fi

# Test that the command fails when given a graph with dependency conflicts
if fromager -v graph to-constraints "$SCRIPTDIR/graph-with-dependency-conflict.json" -o "$OUTDIR/constraints.txt"; then
    echo "Command should have failed when given a graph with dependency conflicts, instead got:" 1>&2
    grep docling "$OUTDIR/constraints.txt" 1>&2
    pass=false
fi

$pass
