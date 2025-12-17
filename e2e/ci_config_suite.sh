#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# CI wrapper script for all configuration/settings-related e2e tests
# This script runs multiple configuration tests sequentially to reduce CI job count
# while preserving the ability to run individual tests during development.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/ci_suite_framework.sh"

init_suite "Configuration Test Suite" "configuration/settings tests"

# Configuration and settings tests
test_section "configuration tests"
run_test "build_settings"
run_test "override"
run_test "extra_metadata"
run_test "lint_requirements"

finish_suite
