#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# CI wrapper script for all bootstrap-parallel-related e2e tests
# This script runs multiple bootstrap parallel tests sequentially to reduce CI job count
# while preserving the ability to run individual tests during development.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/ci_suite_framework.sh"

init_suite "Bootstrap Parallel Test Suite" "bootstrap-parallel tests"

# Bootstrap parallel tests
test_section "bootstrap parallel tests"
run_test "bootstrap_parallel"
run_test "bootstrap_parallel_git_url"
run_test "bootstrap_parallel_git_url_tag"

finish_suite
