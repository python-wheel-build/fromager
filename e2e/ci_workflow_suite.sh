#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# CI wrapper script for all workflow/pipeline-related e2e tests
# This script runs multiple workflow tests sequentially to reduce CI job count
# while preserving the ability to run individual tests during development.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/ci_suite_framework.sh"

init_suite "Workflow Test Suite" "workflow/pipeline tests"

# Workflow and pipeline tests
test_section "graph/constraints workflow tests"
run_test "graph_to_constraints"
run_test "migrate_graph"

test_section "sequence/ordering tests"
run_test "download_sequence"
run_test "optimize_build"

test_section "hook workflow tests"
run_test "post_bootstrap_hook"

test_section "server/deployment tests"
run_test "prebuilt_wheels_alt_server"

test_section "diagnostic tests"
run_test "report_missing_dependency"

finish_suite
