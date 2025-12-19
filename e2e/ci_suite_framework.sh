#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Common framework for CI test suites
# This provides shared functionality for running multiple e2e tests in sequence

set -e
set -o pipefail

# Global variables for tracking test results
FAILED_TESTS=()
TOTAL_TESTS=0
SUITE_NAME=""
SUITE_DESCRIPTION=""

# Initialize a test suite
# Usage: init_suite "Suite Name" "Description of what this suite tests"
init_suite() {
    SUITE_NAME="$1"
    SUITE_DESCRIPTION="$2"
    FAILED_TESTS=()
    TOTAL_TESTS=0

    echo "=========================================="
    echo "CI $SUITE_NAME"
    echo "Running $SUITE_DESCRIPTION sequentially"
    echo "=========================================="
}

# Run a single test with clean environment
# Usage: run_test "test_name_without_prefix"
run_test() {
    local test_name="$1"
    local test_script="$SCRIPTDIR/test_${test_name}.sh"

    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    echo ""
    echo "=========================================="
    echo "Running: $test_name"
    echo "Script: $test_script"
    echo "=========================================="

    if [ ! -f "$test_script" ]; then
        echo "ERROR: Test script not found: $test_script"
        FAILED_TESTS+=("$test_name (script not found)")
        return 1
    fi

    # Clean environment before each test to prevent interference
    clean_test_environment "$test_name"

    # Run the test
    if "$test_script"; then
        echo "PASSED: $test_name"
    else
        echo "FAILED: $test_name"
        FAILED_TESTS+=("$test_name")
        # Continue running other tests instead of exiting immediately
        # This provides more comprehensive feedback in CI
    fi
}

# Clean test environment before each test to prevent interference
# Usage: clean_test_environment "test_name"
clean_test_environment() {
    local test_name="$1"

    echo "Cleaning environment before test: $test_name"

    # Remove e2e output directory
    local outdir
    outdir="$(dirname "$SCRIPTDIR")/e2e-output"
    if [ -d "$outdir" ]; then
        echo "Removing existing e2e-output directory..."
        rm -rf "$outdir" || true
    fi

    # Remove and recreate hatch e2e environment to ensure clean state
    echo "Removing hatch e2e environment..."
    hatch env remove e2e 2>/dev/null || true

    echo "Environment cleaned for test: $test_name"
}

# Print a section header for organizing related tests
# Usage: test_section "Section Description"
test_section() {
    echo ""
    echo "Running $1..."
}

# Print final summary and exit with appropriate code
# Usage: finish_suite
finish_suite() {
    echo ""
    echo "=========================================="
    echo "CI $SUITE_NAME Summary"
    echo "=========================================="
    echo "Total tests run: $TOTAL_TESTS"
    echo "Passed: $((TOTAL_TESTS - ${#FAILED_TESTS[@]}))"
    echo "Failed: ${#FAILED_TESTS[@]}"

    if [ ${#FAILED_TESTS[@]} -gt 0 ]; then
        echo ""
        echo "Failed tests:"
        for test in "${FAILED_TESTS[@]}"; do
            echo "  - $test"
        done
        echo ""
        echo "To debug individual failures, run the specific test script:"
        for test in "${FAILED_TESTS[@]}"; do
            test_name=$(echo "$test" | cut -d' ' -f1)
            echo "  ./e2e/test_${test_name}.sh"
        done
        exit 1
    else
        echo "All tests in $SUITE_NAME passed!"
    fi
}
