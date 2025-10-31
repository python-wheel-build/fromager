#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests the fromager pypi-info command

set -e
set -u
set -o pipefail

pass=true

echo "Testing fromager pypi-info command..."

# Test 1: Get info for an existing package (requests)
echo "Test 1: Get info for requests package"
if output=$(fromager pypi-info requests 2>&1); then
  if echo "$output" | grep -q "Package: requests" && \
     echo "$output" | grep -q "Found on PyPI: Yes" && \
     echo "$output" | grep -q "License:" && \
     echo "$output" | grep -q "Has source distribution (sdist):" && \
     echo "$output" | grep -q "Has wheel:"; then
    echo "PASS: Test 1 passed"
  else
    echo "FAIL: Test 1 failed - missing expected output" 1>&2
    echo "Output: $output" 1>&2
    pass=false
  fi
else
  echo "FAIL: Test 1 failed - command failed" 1>&2
  echo "Output: $output" 1>&2
  pass=false
fi

# Test 2: Get info for a specific version
echo "Test 2: Get info for requests==2.32.0"
if output=$(fromager pypi-info "requests==2.32.0" 2>&1); then
  if echo "$output" | grep -q "Version: 2.32.0"; then
    echo "PASS: Test 2 passed - specific version found"
  else
    echo "FAIL: Test 2 failed - wrong version in output" 1>&2
    echo "Output: $output" 1>&2
    pass=false
  fi
else
  if echo "$output" | grep -q "not found on PyPI"; then
    echo "PASS: Test 2 passed - version not found (expected for older versions)"
  else
    echo "FAIL: Test 2 failed with unexpected error" 1>&2
    echo "Output: $output" 1>&2
    pass=false
  fi
fi

# Test 3: Get info for a non-existent package
echo "Test 3: Get info for non-existent package"
if output=$(fromager pypi-info nonexistentpackage123456789 2>&1); then
  echo "FAIL: Test 3 failed - should have failed for non-existent package" 1>&2
  echo "Output: $output" 1>&2
  pass=false
else
  if echo "$output" | grep -q "not found on PyPI"; then
    echo "PASS: Test 3 passed - non-existent package correctly handled"
  else
    echo "FAIL: Test 3 failed - wrong error message" 1>&2
    echo "Output: $output" 1>&2
    pass=false
  fi
fi

# Test 4: Test with invalid package specification
echo "Test 4: Test with invalid package specification"
if output=$(fromager pypi-info "invalid[package[spec" 2>&1); then
  echo "FAIL: Test 4 failed - should have failed for invalid spec" 1>&2
  echo "Output: $output" 1>&2
  pass=false
else
  if echo "$output" | grep -q "Invalid package specification"; then
    echo "PASS: Test 4 passed - invalid spec correctly handled"
  else
    echo "FAIL: Test 4 failed - wrong error message" 1>&2
    echo "Output: $output" 1>&2
    pass=false
  fi
fi

# Test 5: Test with unsupported version specification
echo "Test 5: Test with unsupported version specification"
if output=$(fromager pypi-info "requests>=2.0.0" 2>&1); then
  echo "FAIL: Test 5 failed - should have failed for unsupported version spec" 1>&2
  echo "Output: $output" 1>&2
  pass=false
else
  if echo "$output" | grep -q "Only exact version specifications"; then
    echo "PASS: Test 5 passed - unsupported version spec correctly handled"
  else
    echo "FAIL: Test 5 failed - wrong error message" 1>&2
    echo "Output: $output" 1>&2
    pass=false
  fi
fi

echo "All info command tests completed."

if $pass; then
  echo "ALL TESTS PASSED"
  exit 0
else
  echo "SOME TESTS FAILED"
  exit 1
fi