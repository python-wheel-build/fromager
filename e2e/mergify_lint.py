#!/usr/bin/env python

import itertools
import pathlib
import re
import sys

import yaml
from packaging.version import Version

# Parse the mergify settings to find the rules that are in place.
mergify_settings_file = pathlib.Path(".mergify.yml")
mergify_settings = yaml.safe_load(mergify_settings_file.read_text(encoding="utf8"))
existing_jobs = set()
for item in mergify_settings["pull_request_rules"]:
    if item["name"] == "Automatic merge on approval":
        conditions = item["conditions"][0]["and"]
        # Look for 'check-success=e2e (something, something, something, something)'
        for rule in conditions:
            if not isinstance(rule, str):
                continue
            if not rule.startswith("check-success=e2e"):
                continue
            parameters = rule.partition(" ")[-1]
            existing_jobs.add(parameters)
        if not existing_jobs:
            raise ValueError(f"Could not find e2e jobs in {mergify_settings_file}")
print("existing jobs:\n  ", "\n  ".join(str(j) for j in sorted(existing_jobs)), sep="")

# Parse the github actions file to find the test jobs that are defined.
github_actions_file = pathlib.Path(".github/workflows/test.yaml")
github_actions = yaml.safe_load(github_actions_file.read_text(encoding="utf8"))
matrix = github_actions["jobs"]["e2e"]["strategy"]["matrix"]
python_versions = list(sorted(matrix["python-version"], key=Version))
rust_versions = list(sorted(matrix["rust-version"], key=Version))
test_scripts = set(matrix["test-script"])
print("found test scripts:\n  ", "\n  ".join(sorted(test_scripts)), sep="")
os_versions = list(sorted(matrix["os"]))
os_versions.remove("macos-latest")

e2e_dir = pathlib.Path("e2e")
# Look for CI suite scripts instead of individual test scripts
ci_suite_jobs = set(
    script.name[:-len(".sh")] for script in e2e_dir.glob("ci_*_suite.sh")
)
print("found CI suite scripts:\n  ", "\n  ".join(sorted(ci_suite_jobs)), sep="")

# Also find all individual e2e test scripts to ensure they're all covered
individual_e2e_scripts = set(
    script.name[len("test_") : -len(".sh")] for script in e2e_dir.glob("test_*.sh")
)
print("found individual e2e scripts:\n  ", "\n  ".join(sorted(individual_e2e_scripts)), sep="")

# Remember if we should fail so we can apply all of the rules and then
# exit with an error.
RC = 0

# Require test jobs for every CI suite script.
for script_name in sorted(ci_suite_jobs.difference(test_scripts)):
    print(f"ERROR: {script_name} not in the matrix in {github_actions_file}")
    RC = 1

# Check that all individual e2e scripts are referenced in CI suite scripts
print("\nChecking that all individual e2e tests are covered by CI suites...")
referenced_scripts = set()
for ci_suite_file in e2e_dir.glob("ci_*_suite.sh"):
    content = ci_suite_file.read_text(encoding="utf8")
    # Look for run_test "script_name" calls (excluding commented lines)
    for line in content.split("\n"):
        # Skip lines that start with # (comments)
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for match in re.finditer(r'run_test\s+"([^"]+)"', line):
            referenced_scripts.add(match.group(1))

print("scripts referenced in CI suites:\n  ", "\n  ".join(sorted(referenced_scripts)), sep="")

# Find any individual e2e scripts that aren't referenced in any CI suite
unreferenced_scripts = individual_e2e_scripts.difference(referenced_scripts)
if unreferenced_scripts:
    print("\nERROR: The following e2e scripts are not referenced in any CI suite:")
    for script in sorted(unreferenced_scripts):
        print(f"  - {script}")
    print("Please add these scripts to the appropriate CI suite script.")
    RC = 1
else:
    print("✓ All individual e2e scripts are covered by CI suites!")

# We expect a job for every combination of python version, rust
# version, and test script.
expected_jobs = set(
    str(combo).replace("'", "")
    for combo in itertools.product(
        python_versions,
        rust_versions,
        test_scripts,
        os_versions,
    )
)
# for macOS, only expect latest Python version and latest Rust version
expected_jobs.update(set(
    str(combo).replace("'", "")
    for combo in itertools.product(
        python_versions[-1:],
        rust_versions[-1:],
        test_scripts,
        ["macos-latest"],
    )
))
if not expected_jobs.difference(existing_jobs):
    print("found rules for all expected jobs!")
for job_name in sorted(expected_jobs.difference(existing_jobs)):
    print(
        f'ERROR: there is no rule requiring "check-success=e2e {job_name}" in {mergify_settings_file}'
    )
    RC = 1

if RC:
    print(f"\njobs list to paste into {mergify_settings_file}:\n")
    for job_name in sorted(expected_jobs):
        print(f"          - check-success=e2e {job_name}")
    print()

sys.exit(RC)
