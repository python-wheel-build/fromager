#!/usr/bin/env python

import itertools
import pathlib
import sys

import yaml

# Parse the mergify settings to find the rules that are in place.
mergify_settings_file = pathlib.Path('.mergify.yml')
mergify_settings = yaml.safe_load(mergify_settings_file.read_text(encoding='utf8'))
required_jobs = set()
for item in mergify_settings['pull_request_rules']:
    if item['name'] == 'Automatic merge on approval':
        conditions = item['conditions'][0]['and']
        # Look for 'check-success=e2e (something, something, something)'
        for rule in conditions:
            if not isinstance(rule, str):
                continue
            if not rule.startswith('check-success=e2e'):
                continue
            parameters = rule.partition(' ')[-1]
            required_jobs.add(parameters)
        if not required_jobs:
            raise ValueError(f'Could not find e2e jobs in {mergify_settings_file}')
print('found mergify required jobs:', required_jobs)

# Parse the github actions file to find the test jobs that are defined.
github_actions_file = pathlib.Path('.github/workflows/test.yaml')
github_actions = yaml.safe_load(github_actions_file.read_text(encoding='utf8'))
matrix = github_actions['jobs']['e2e']['strategy']['matrix']
python_versions = list(sorted(matrix['python-version']))
rust_versions = list(sorted(matrix['rust-version']))
test_scripts = set(matrix['test-script'])
print('found test scripts:', test_scripts)

e2e_dir = pathlib.Path('e2e')
e2e_jobs = set(
    script.name[len('test_'):-len('.sh')]
    for script in e2e_dir.glob('test_*.sh')
)
print('found job scripts:', e2e_jobs)

# Remember if we should fail so we can apply all of the rules and then
# exit with an error.
RC = 0

# Require test jobs for every script.
for script_name in sorted(e2e_jobs.difference(test_scripts)):
    print(f'ERROR: {script_name} not in the matrix in {github_actions_file}')
    RC =1

# We expect a job for every combination of python version, rust
# version, and test script.
expected_jobs = set(
    str(combo).replace("'", '')
    for combo in itertools.product(python_versions, rust_versions, test_scripts)
)
for job_name in sorted(expected_jobs.difference(required_jobs)):
    print(f'ERROR: there is no rule requiring "check-success=e2e {job_name}" in {mergify_settings_file}')
    RC = 1

sys.exit(RC)
