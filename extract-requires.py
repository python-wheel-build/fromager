import argparse
import os
import subprocess
import sys

import pyproject_hooks
import toml
from packaging import metadata

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


def get_build_backend_hook_caller(pyproject_toml):
    if (not 'build-system' in pyproject_toml or
        not 'build-backend' in pyproject_toml['build-system']):
        return None
    return pyproject_hooks.BuildBackendHookCaller(
        source_dir=".",
        build_backend=pyproject_toml['build-system']['build-backend'],
        backend_path=pyproject_toml['build-system'].get('backend-path', None),
        runner=logging_subprocess_runner,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-system", action=argparse.BooleanOptionalAction)
    parser.add_argument("--build-backend", action=argparse.BooleanOptionalAction)
    args = parser.parse_args()

    pyproject_toml = toml.loads(sys.stdin.read())
    hook_caller = get_build_backend_hook_caller(pyproject_toml)
    if hook_caller is None:
        raise Exception('No build-system in pyproject.toml - FIXME implement the legacy behaviour of running setup.py')

    requires = []
    if not (args.build_system or args.build_backend):
        requires.extend(pyproject_toml.get('project', {}).get('dependencies', []))

        metadata_path = hook_caller.prepare_metadata_for_build_wheel("./")

        with open(os.path.join(metadata_path, "METADATA"), "r") as f:
            parsed = metadata.Metadata.from_email(f.read(), validate=False)
            for r in (parsed.requires_dist or []):
                if not r.marker:
                    requires.append(str(r))
    elif args.build_system:
        requires.extend(pyproject_toml.get('build-system', {}).get('requires', []))
    elif args.build_backend:
        requires.extend(hook_caller.get_requires_for_build_wheel())

    for req in requires:
        print(f"{req}")
