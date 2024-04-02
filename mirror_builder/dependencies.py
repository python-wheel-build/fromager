import logging
import os

import pyproject_hooks
import tomli
from packaging import markers, metadata
from packaging.requirements import Requirement

from . import external_commands

logger = logging.getLogger(__name__)


def get_build_system_dependencies(req, sdist_root_dir):
    logger.debug('getting build system dependencies for %s in %s',
                 req, sdist_root_dir)
    pyproject_toml = _get_pyproject_contents(sdist_root_dir)
    requires = set()
    for r in get_build_backend(pyproject_toml)['requires']:
        if evaluate_marker(Requirement(r)):
            requires.add(r)
    return requires


def get_build_backend_dependencies(req, sdist_root_dir):
    logger.debug('getting build backend dependencies for %s in %s',
                 req, sdist_root_dir)
    pyproject_toml = _get_pyproject_contents(sdist_root_dir)
    requires = set()
    hook_caller = get_build_backend_hook_caller(sdist_root_dir, pyproject_toml)
    for r in hook_caller.get_requires_for_build_wheel():
        if evaluate_marker(Requirement(r)):
            requires.add(r)
    return requires


def get_install_dependencies(req, sdist_root_dir):
    logger.debug('getting installation dependencies for %s in %s',
                 req, sdist_root_dir)
    original_requirement = Requirement(req)
    pyproject_toml = _get_pyproject_contents(sdist_root_dir)
    requires = set()
    hook_caller = get_build_backend_hook_caller(sdist_root_dir, pyproject_toml)
    metadata_path = hook_caller.prepare_metadata_for_build_wheel(sdist_root_dir)
    with open(os.path.join(sdist_root_dir, metadata_path, "METADATA"), "r") as f:
        parsed = metadata.Metadata.from_email(f.read(), validate=False)
        for r in (parsed.requires_dist or []):
            if evaluate_marker(r, original_requirement.extras):
                requires.add(str(r))
    return requires


def _get_pyproject_contents(sdist_root_dir):
    pyproject_toml_filename = sdist_root_dir / 'pyproject.toml'
    if not os.path.exists(pyproject_toml_filename):
        return {}
    return tomli.loads(pyproject_toml_filename.read_text())


# From pypa/build/src/build/__main__.py
_DEFAULT_BACKEND = {
    'build-backend': 'setuptools.build_meta:__legacy__',
    'backend-path': None,
    'requires': ['setuptools >= 40.8.0'],
}


def get_build_backend(pyproject_toml):
    if ('build-system' not in pyproject_toml or
        'build-backend' not in pyproject_toml['build-system']):
        return _DEFAULT_BACKEND
    else:
        return {
            'build-backend': pyproject_toml['build-system']['build-backend'],
            'backend-path': pyproject_toml['build-system'].get('backend-path', None),
            'requires': pyproject_toml['build-system'].get('requires', []),
        }


def get_build_backend_hook_caller(sdist_root_dir, pyproject_toml):
    backend = get_build_backend(pyproject_toml)
    return pyproject_hooks.BuildBackendHookCaller(
        source_dir=sdist_root_dir,
        build_backend=backend['build-backend'],
        backend_path=backend['backend-path'],
        runner=external_commands.run,
    )


def evaluate_marker(req, extras=None):
    if not req.marker:
        return True

    default_env = markers.default_environment()
    if not extras:
        marker_envs = [default_env]
    else:
        marker_envs = [default_env.copy() | {'extra': e} for e in extras]

    for marker_env in marker_envs:
        if req.marker.evaluate(marker_env):
            logger.debug(f'adding {req} -- marker evaluates true with extras={extras} and default_env={default_env}')
            return True

    logger.debug(f'ignoring {req} -- marker evaluates false with extras={extras} and default_env={default_env}')
    return False
