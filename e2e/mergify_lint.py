#!/usr/bin/env python

import itertools
import pathlib
import sys

import yaml

# Parse the mergify settings to find the rules that are in place.
mergify_settings_file = pathlib.Path(".mergify.yml")
mergify_settings = yaml.safe_load(mergify_settings_file.read_text(encoding="utf8"))


def get_existing_jobs(mergify_settings, name_prefix):
    test_prefix = f"check-success={name_prefix} "
    existing_jobs = set()
    for item in mergify_settings["pull_request_rules"]:
        if item["name"] == "Automatic merge on approval":
            conditions = item["conditions"][0]["and"]
            # Look for 'check-success={name_prefix} (something, something, something, something)'
            for rule in conditions:
                if not isinstance(rule, str):
                    continue
                if not rule.startswith(test_prefix):
                    continue
                parameters = rule.partition(" ")[-1]
                existing_jobs.add(parameters)
    return existing_jobs


def check_jobs(mergify_settings, name_prefix, existing_jobs):
    print(f"\nchecking {name_prefix}")
    print(
        f"existing {name_prefix} jobs:\n  ",
        "\n  ".join(str(j) for j in sorted(existing_jobs)),
        sep="",
    )

    # Parse the github actions file to find the test jobs that are defined.
    github_actions_file = pathlib.Path(".github/workflows/test.yaml")
    github_actions = yaml.safe_load(github_actions_file.read_text(encoding="utf8"))

    e2e_matrix = github_actions["jobs"][name_prefix]["strategy"]["matrix"]
    e2e_python_versions = list(sorted(e2e_matrix["python-version"]))
    e2e_rust_versions = list(sorted(e2e_matrix["rust-version"]))
    e2e_test_scripts = set(e2e_matrix["test-script"])
    print(
        f"found {name_prefix} test scripts:\n  ",
        "\n  ".join(sorted(e2e_test_scripts)),
        sep="",
    )

    e2e_dir = pathlib.Path("e2e")
    e2e_jobs = set(
        script.name[len("test_") : -len(".sh")] for script in e2e_dir.glob("test_*.sh")
    )
    print("found job scripts:\n  ", "\n  ".join(sorted(e2e_jobs)), sep="")

    # Remember if we should fail so we can apply all of the rules and then
    # exit with an error.
    RC = 0

    # Require test jobs for every script.
    for script_name in sorted(e2e_jobs.difference(e2e_test_scripts)):
        print(f"ERROR: {script_name} not in the e2e matrix in {github_actions_file}")
        RC = 1

    # We expect a job for every combination of python version, rust
    # version, and test script.
    expected_jobs = set(
        str(combo).replace("'", "")
        for combo in itertools.product(
            e2e_python_versions,
            e2e_rust_versions,
            e2e_test_scripts,
        )
    )
    if not expected_jobs.difference(existing_jobs):
        print(f"found rules for all expected {name_prefix} jobs!")
    for job_name in sorted(expected_jobs.difference(existing_jobs)):
        print(
            f'ERROR: there is no rule requiring "check-success={name_prefix} {job_name}" in {mergify_settings_file}'
        )
        RC = 1

    return (RC, expected_jobs)


RC = 0

existing_e2e_jobs = get_existing_jobs(
    mergify_settings=mergify_settings,
    name_prefix="e2e",
)
new_rc, expected_e2e_jobs = check_jobs(
    mergify_settings,
    "e2e",
    existing_e2e_jobs,
)
RC = RC or new_rc

existing_macos_jobs = get_existing_jobs(
    mergify_settings=mergify_settings,
    name_prefix="e2e-macos",
)
new_rc, expected_macos_jobs = check_jobs(
    mergify_settings,
    "e2e-macos",
    existing_macos_jobs,
)
RC = RC or new_rc

if RC:
    print(f"\njobs list to paste into {mergify_settings_file}:\n")
    for job_name in sorted(expected_e2e_jobs):
        print(f"          - check-success=e2e {job_name}")
    for job_name in sorted(expected_macos_jobs):
        print(f"          - check-success=e2e-macos {job_name}")
    print('          - "-draft"')
    print()

sys.exit(RC)
