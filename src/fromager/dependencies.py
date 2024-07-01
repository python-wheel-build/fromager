import copy
import logging
import os
import pathlib
import shutil
import typing

import pkginfo
import pyproject_hooks
import toml
from packaging import markers, metadata
from packaging.requirements import Requirement

from . import context, external_commands, overrides

logger = logging.getLogger(__name__)


def get_build_system_dependencies(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
) -> set[Requirement]:
    logger.info(
        f"{req.name}: getting build system dependencies for {req} in {sdist_root_dir}"
    )
    dep_func = overrides.find_override_method(req.name, "get_build_system_dependencies")
    if not dep_func:
        dep_func = default_get_build_system_dependencies
    deps = _filter_requirements(req, dep_func(ctx, req, sdist_root_dir))
    return deps


def _filter_requirements(
    req: Requirement, requirements: typing.Iterable[Requirement]
) -> set[Requirement]:
    requires = set()
    for r in requirements:
        if not isinstance(r, Requirement):
            r = Requirement(r)
        if evaluate_marker(r, req.extras):
            requires.add(r)
    return requires


def default_get_build_system_dependencies(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
) -> typing.Iterable[Requirement]:
    pyproject_toml = get_pyproject_contents(sdist_root_dir)
    return get_build_backend(pyproject_toml)["requires"]


def get_build_backend_dependencies(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
) -> set[Requirement]:
    logger.info(
        f"{req.name}: getting build backend dependencies for {req} in {sdist_root_dir}"
    )
    dep_func = overrides.find_override_method(
        req.name, "get_build_backend_dependencies"
    )
    if not dep_func:
        dep_func = default_get_build_backend_dependencies
    deps = _filter_requirements(req, dep_func(ctx, req, sdist_root_dir))
    return deps


def default_get_build_backend_dependencies(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
) -> set[Requirement]:
    pyproject_toml = get_pyproject_contents(sdist_root_dir)
    extra_environ = overrides.extra_environ_for_pkg(ctx.envs_dir, req.name, ctx.variant)
    hook_caller = get_build_backend_hook_caller(
        sdist_root_dir, pyproject_toml, override_environ=extra_environ
    )
    return hook_caller.get_requires_for_build_wheel()


def get_build_sdist_dependencies(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
) -> set[Requirement]:
    logger.info(
        f"{req.name}: getting build sdist dependencies for {req} in {sdist_root_dir}"
    )
    dep_func = overrides.find_override_method(req.name, "get_build_sdist_dependencies")
    if not dep_func:
        dep_func = default_get_build_sdist_dependencies
    deps = _filter_requirements(req, dep_func(ctx, req, sdist_root_dir))
    return deps


def default_get_build_sdist_dependencies(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
) -> set[Requirement]:
    pyproject_toml = get_pyproject_contents(sdist_root_dir)
    extra_environ = overrides.extra_environ_for_pkg(ctx.envs_dir, req.name, ctx.variant)
    hook_caller = get_build_backend_hook_caller(
        sdist_root_dir, pyproject_toml, override_environ=extra_environ
    )
    return hook_caller.get_requires_for_build_wheel()


def get_install_dependencies(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
) -> set[Requirement]:
    logger.info(
        f"{req.name}: getting installation dependencies for {req} in {sdist_root_dir}"
    )
    dep_func = overrides.find_override_method(req.name, "get_install_dependencies")
    if not dep_func:
        dep_func = default_get_install_dependencies
    deps = _filter_requirements(req, dep_func(ctx, req, sdist_root_dir))
    return deps


def get_install_dependencies_of_wheel(
    req: Requirement, wheel_filename: pathlib.Path
) -> set[Requirement]:
    logger.info(f"{req.name}: getting installation dependencies from {wheel_filename}")
    wheel = pkginfo.Wheel(wheel_filename)
    return _filter_requirements(req, wheel.requires_dist)


def default_get_install_dependencies(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
) -> set[Requirement]:
    pyproject_toml = get_pyproject_contents(sdist_root_dir)
    requires = set()
    extra_environ = overrides.extra_environ_for_pkg(ctx.envs_dir, req.name, ctx.variant)
    hook_caller = get_build_backend_hook_caller(
        sdist_root_dir, pyproject_toml, override_environ=extra_environ
    )

    # Clean up any existing dist-info so we don't get an error regenerating it.
    for info_dir in sdist_root_dir.glob("*.dist-info"):
        logger.debug(f"{req.name}: removing existing dist-info dir {info_dir}")
        shutil.rmtree(info_dir)

    metadata_path = hook_caller.prepare_metadata_for_build_wheel(sdist_root_dir)
    with open(os.path.join(sdist_root_dir, metadata_path, "METADATA"), "r") as f:
        parsed = metadata.Metadata.from_email(f.read(), validate=False)
        for r in parsed.requires_dist or []:
            if evaluate_marker(r, req.extras):
                requires.add(r)
    return requires


def get_pyproject_contents(sdist_root_dir: pathlib.Path) -> dict:
    pyproject_toml_filename = sdist_root_dir / "pyproject.toml"
    if not os.path.exists(pyproject_toml_filename):
        return {}
    return toml.loads(pyproject_toml_filename.read_text())


# From pypa/build/src/build/__main__.py
_DEFAULT_BACKEND = {
    "build-backend": "setuptools.build_meta:__legacy__",
    "backend-path": None,
    "requires": ["setuptools >= 40.8.0"],
}


def get_build_backend(pyproject_toml: dict) -> dict:
    # Build a set of defaults. Use a copy to ensure that if anything
    # modifies the values returned by this function our defaults are
    # not changed.
    backend_settings = copy.deepcopy(_DEFAULT_BACKEND)

    # Override it with local settings. This allows for some projects
    # like pyarrow, that don't have 'build-backend' set but *do* have
    # 'requires' set.
    for key in ["build-backend", "backend-path", "requires"]:
        if key in pyproject_toml.get("build-system", {}):
            backend_settings[key] = pyproject_toml["build-system"][key]

    return backend_settings


def get_build_backend_hook_caller(
    sdist_root_dir: pathlib.Path, pyproject_toml: dict, override_environ: dict
) -> pyproject_hooks.BuildBackendHookCaller:
    backend = get_build_backend(pyproject_toml)

    def _run_hook_with_extra_environ(cmd, cwd=None, extra_environ=None):
        """The BuildBackendHookCaller is going to pass extra_environ
        and our build system may want to set some values, too. Merge
        the 2 sets of values before calling the actual runner function.
        """
        full_environ = {}
        if extra_environ is not None:
            full_environ.update(extra_environ)
        full_environ.update(override_environ)
        return external_commands.run(cmd, cwd=cwd, extra_environ=full_environ)

    return pyproject_hooks.BuildBackendHookCaller(
        source_dir=sdist_root_dir,
        build_backend=backend["build-backend"],
        backend_path=backend["backend-path"],
        runner=_run_hook_with_extra_environ,
    )


def evaluate_marker(req: Requirement, extras: dict | None = None) -> bool:
    if not req.marker:
        return True

    default_env = markers.default_environment()
    if not extras:
        marker_envs = [default_env]
    else:
        marker_envs = [default_env.copy() | {"extra": e} for e in extras]

    for marker_env in marker_envs:
        if req.marker.evaluate(marker_env):
            logger.debug(
                f"adding {req} -- marker evaluates true with extras={extras} and default_env={default_env}"
            )
            return True

    logger.debug(
        f"ignoring {req} -- marker evaluates false with extras={extras} and default_env={default_env}"
    )
    return False
