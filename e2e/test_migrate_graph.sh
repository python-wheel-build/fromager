#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests migration from old to new graphs

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

fromager graph migrate-graph $SCRIPTDIR/migrate_graph/old_graph.json -o $OUTDIR/new_graph.json

fromager graph to-constraints $OUTDIR/new_graph.json -o $OUTDIR/new_graph_constraints.txt

pass=true
diff $SCRIPTDIR/migrate_graph/old_constraints.txt $OUTDIR/new_graph_constraints.txt
if [ $? -ne 0 ]; then
    echo "constraints file from old graph and new graph differ"
    pass=false
fi;

$pass