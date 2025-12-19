#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# CI wrapper script for all build-related e2e tests
# This script runs multiple build tests sequentially to reduce CI job count
# while preserving the ability to run individual tests during development.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/ci_suite_framework.sh"

init_suite "Build Test Suite" "build-related tests"

# Build tests in logical order
test_section "core build tests"
run_test "build"
run_test "build_order"
run_test "build_steps"

test_section "advanced build tests"
run_test "build_parallel"
run_test "build_sequence_git_url"

finish_suite
