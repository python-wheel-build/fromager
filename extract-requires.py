import argparse
import os
import subprocess
import sys

import pyproject_hooks
import tomli
from packaging import markers
from packaging import metadata
from packaging.requirements import Requirement

# Extract requirements from a pyproject.toml
#
# By default, extract the list of install-time dependencies by preparing
# wheel metadata and extracting Requires-Dist from that
# The --build-system option extracts the build-system.requires section
# The --build-backend option is used to extract requirements using the
# build backend get_requires_for_build_wheel hook (PEP 517)

# based on pyproject_hooks/_impl.py: quiet_subprocess_runner
def logging_subprocess_runner(cmd, cwd=None, extra_environ=None):
    """Call the subprocess while logging output to stderr.

    This uses :func:`subprocess.check_output` under the hood.
    """
    env = os.environ.copy()
    if extra_environ:
        env.update(extra_environ)

    completed = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = completed.stdout.decode('utf-8') if completed.stdout else ''
    if output:
        print(output, file=sys.stderr)
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, cmd, output)


# From pypa/build/src/build/__main__.py
_DEFAULT_BACKEND = {
    'build-backend': 'setuptools.build_meta:__legacy__',
    'backend-path': None,
    'requires': ['setuptools >= 40.8.0'],
}


def get_build_backend(pyproject_toml):
    if (not 'build-system' in pyproject_toml or
        not 'build-backend' in pyproject_toml['build-system']):
        return _DEFAULT_BACKEND
    else:
        return {
            'build-backend': pyproject_toml['build-system']['build-backend'],
            'backend-path': pyproject_toml['build-system'].get('backend-path', None),
            'requires': pyproject_toml['build-system'].get('requires', []),
        }


def get_build_backend_hook_caller(pyproject_toml):
    backend = get_build_backend(pyproject_toml)
    return pyproject_hooks.BuildBackendHookCaller(
        source_dir=".",
        build_backend=backend['build-backend'],
        backend_path=backend['backend-path'],
        runner=logging_subprocess_runner,
    )


def evaluate_marker(req, extras=None):
    marker_env = markers.default_environment()
    for extra in extras if extras else [""]:
        if extra:
            marker_env['extra'] = extra
        if (not req.marker) or req.marker.evaluate(marker_env):
            print(f'adding {req} via extra="{extra}"', file=sys.stderr)
            return True
        else:
            print(f'ignoring {req} because marker evaluates false with context {marker_env}', file=sys.stderr)
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-system", action=argparse.BooleanOptionalAction)
    parser.add_argument("--build-backend", action=argparse.BooleanOptionalAction)
    parser.add_argument("original_requirement")
    args = parser.parse_args()

    original_requirement = Requirement(args.original_requirement)

    if not os.path.exists('pyproject.toml'):
        pyproject_toml = {}
    else:
        with open('pyproject.toml', 'r') as f:
            pyproject_toml = tomli.loads(f.read())
    hook_caller = get_build_backend_hook_caller(pyproject_toml)

    requires = set()
    if not (args.build_system or args.build_backend):
        metadata_path = hook_caller.prepare_metadata_for_build_wheel("./")

        with open(os.path.join(metadata_path, "METADATA"), "r") as f:
            parsed = metadata.Metadata.from_email(f.read(), validate=False)
            for r in (parsed.requires_dist or []):
                if evaluate_marker(r, original_requirement.extras):
                    requires.add(str(r))
    elif args.build_system:
        for r in get_build_backend(pyproject_toml)['requires']:
            if evaluate_marker(Requirement(r)):
                requires.add(r)
    elif args.build_backend:
        for r in hook_caller.get_requires_for_build_wheel():
            if evaluate_marker(Requirement(r)):
                requires.add(r)

    for req in requires:
        print(f"{req}")
