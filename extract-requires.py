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
    if not req.marker:
        return True

    default_env = markers.default_environment()
    if not extras:
        marker_envs = [default_env]
    else:
        marker_envs = [default_env.copy() | {'extra':e} for e in extras]

    for marker_env in marker_envs:
        if req.marker.evaluate(marker_env):
            print(f'adding {req} -- marker evaluates true with extras={extras} and default_env={default_env}',
                  file=sys.stderr)
            return True

    print(f'ignoring {req} -- marker evaluates false with extras={extras} and default_env={default_env}',
          file=sys.stderr)
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
