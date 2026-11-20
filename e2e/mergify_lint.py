#!/usr/bin/env python

import itertools
import pathlib
import re
import sys
import typing

import yaml
from packaging.version import Version

# Parse the mergify settings to find the rules that are in place.
mergify_settings_file = pathlib.Path(".mergify.yml")
mergify_settings = yaml.safe_load(mergify_settings_file.read_text(encoding="utf8"))
# Matches 'check-success=e2e (3.12, 1.75, ci_build_suite, ubuntu-latest)',
# with or without spaces around '=', and captures the part in parentheses.
E2E_CHECK = re.compile(r"^check-success\s*=\s*e2e\s*(\(.*\))$")
# The docs-only group is the one that limits which files changed.
DOCS_ONLY_MARKER = re.compile(r"^-files\s*~=")


def e2e_job(condition: str) -> str | None:
    """Return the e2e job parameters for an e2e check condition, else None."""
    match = E2E_CHECK.match(condition.strip())
    return match.group(1) if match else None


def iter_conditions(conditions: list[typing.Any]) -> typing.Iterator[str]:
    """Yield every string condition, descending into and/or/not groups."""
    for rule in conditions:
        if isinstance(rule, str):
            yield rule
        elif isinstance(rule, dict):
            for nested in rule.values():
                yield from iter_conditions(nested)


def find_ci_checks(conditions: list[typing.Any]) -> list[str]:
    """Return the checks of the full CI group in the queue conditions.

    The queue conditions must have one ``or`` with two ``and`` groups: a
    docs-only group (it has a ``-files~=`` condition) and the full CI group.
    E2e checks must only appear in the full CI group, as plain strings.
    """
    candidates: list[tuple[list[str], list[typing.Any]]] = []
    for rule in conditions:
        if not (isinstance(rule, dict) and list(rule) == ["or"]):
            continue
        groups = rule["or"]
        if len(groups) != 2 or not all(
            isinstance(g, dict) and list(g) == ["and"] for g in groups
        ):
            continue
        docs = [
            g["and"]
            for g in groups
            if any(
                isinstance(c, str) and DOCS_ONLY_MARKER.match(c.strip())
                for c in g["and"]
            )
        ]
        if len(docs) == 1:
            ci = [g["and"] for g in groups if g["and"] is not docs[0]]
            candidates.append((ci[0], docs[0]))
    if len(candidates) != 1:
        raise ValueError(
            f"expected one 'or' with a full CI group and a docs-only group in "
            f"{mergify_settings_file}, found {len(candidates)}"
        )
    ci_checks, docs_checks = candidates[0]
    if not all(isinstance(c, str) for c in ci_checks):
        raise ValueError(
            f"the CI group in {mergify_settings_file} must only contain plain checks"
        )
    if any(e2e_job(c) for c in iter_conditions(docs_checks)):
        raise ValueError(
            f"the docs-only group in {mergify_settings_file} must not require e2e checks"
        )
    total = sum(1 for c in iter_conditions(conditions) if e2e_job(c))
    found = sum(1 for c in ci_checks if e2e_job(c))
    if total != found:
        raise ValueError(
            f"e2e checks found outside the CI group in {mergify_settings_file}"
        )
    return ci_checks


queue_rule = next(
    item for item in mergify_settings["queue_rules"] if item["name"] == "default"
)
if "merge_conditions" in queue_rule:
    raise ValueError(
        f"{mergify_settings_file}: keep checks in queue_conditions only, "
        "so Mergify checks PRs in place"
    )
existing_jobs = set()
for rule in find_ci_checks(queue_rule["queue_conditions"]):
    job = e2e_job(rule)
    if job:
        existing_jobs.add(job)
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

e2e_dir = pathlib.Path("e2e")
# Look for CI suite scripts instead of individual test scripts
ci_suite_jobs = set(
    script.name[: -len(".sh")] for script in e2e_dir.glob("ci_*_suite.sh")
)
print("found CI suite scripts:\n  ", "\n  ".join(sorted(ci_suite_jobs)), sep="")

# Also find all individual e2e test scripts to ensure they're all covered
individual_e2e_scripts = set(
    script.name[len("test_") : -len(".sh")] for script in e2e_dir.glob("test_*.sh")
)
print(
    "found individual e2e scripts:\n  ",
    "\n  ".join(sorted(individual_e2e_scripts)),
    sep="",
)

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

print(
    "scripts referenced in CI suites:\n  ",
    "\n  ".join(sorted(referenced_scripts)),
    sep="",
)

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
        print(f"              - check-success=e2e {job_name}")
    print()

sys.exit(RC)
