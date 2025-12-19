#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# CI wrapper script for all specialized build-related e2e tests
# This script runs multiple specialized build tests sequentially to reduce CI job count
# while preserving the ability to run individual tests during development.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/ci_suite_framework.sh"

init_suite "Specialized Build Test Suite" "specialized build tests"

# Specialized build tests
test_section "specialized build system tests"
run_test "meson"
run_test "rust_vendor"

test_section "build standard tests"
run_test "pep517_build_sdist"

test_section "platform-specific tests"
run_test "elfdeps"

test_section "hook tests"
run_test "prebuilt_wheel_hook"

finish_suite
