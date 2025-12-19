#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# CI wrapper script for all bootstrap-related e2e tests
# This script runs multiple bootstrap tests sequentially to reduce CI job count
# while preserving the ability to run individual tests during development.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/ci_suite_framework.sh"

init_suite "Bootstrap Test Suite" "standard bootstrap tests (parallel bootstrap tests are in separate suite)"

# Bootstrap tests in logical order - basic first, then variations
test_section "basic bootstrap tests"
run_test "bootstrap"
run_test "bootstrap_extras"
run_test "bootstrap_build_tags"

test_section "bootstrap constraint tests"
run_test "bootstrap_constraints"
run_test "bootstrap_skip_constraints"
run_test "bootstrap_conflicting_requirements"

test_section "bootstrap configuration tests"
run_test "bootstrap_prerelease"
run_test "bootstrap_cache"
run_test "bootstrap_sdist_only"

test_section "bootstrap git URL tests"
run_test "bootstrap_git_url"
run_test "bootstrap_git_url_tag"

finish_suite
