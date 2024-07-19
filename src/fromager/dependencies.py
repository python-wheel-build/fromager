import copy
import logging
import os
import pathlib
import shutil
import typing

import pkginfo
import pyproject_hooks
import toml
from packaging import metadata
from packaging.requirements import Requirement

from . import context, external_commands, overrides, requirements_file

logger = logging.getLogger(__name__)


def get_build_system_dependencies(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
) -> set[Requirement]:
    logger.info(
        f"{req.name}: getting build system dependencies for {req} in {sdist_root_dir}"
    )

    build_system_req_file = sdist_root_dir.parent / "build-system-requirements.txt"
    if build_system_req_file.exists():
        logger.info(
            f"{req.name}: loading build system dependencies from {build_system_req_file.name}"
        )
        return _read_requirements_file(build_system_req_file)

    orig_deps = overrides.find_and_invoke(
        req.name,
        "get_build_system_dependencies",
        default_get_build_system_dependencies,
        ctx=ctx,
        req=req,
        sdist_root_dir=sdist_root_dir,
    )
    deps = _filter_requirements(req, orig_deps)

    _write_requirements_file(
        deps,
        build_system_req_file,
    )
    return deps


def _filter_requirements(
    req: Requirement,
    requirements: typing.Iterable[Requirement],
) -> set[Requirement]:
    requires = set()
    for r in requirements:
        if not isinstance(r, Requirement):
            r = Requirement(r)
        if requirements_file.evaluate_marker(req, r, req.extras):
            requires.add(r)
        else:
            logger.debug(f"{req.name}: ignoring requirement {r}")
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

    build_backend_req_file = sdist_root_dir.parent / "build-backend-requirements.txt"
    if build_backend_req_file.exists():
        logger.info(
            f"{req.name}: loading build backend dependencies from {build_backend_req_file.name}"
        )
        return _read_requirements_file(build_backend_req_file)

    orig_deps = overrides.find_and_invoke(
        req.name,
        "get_build_backend_dependencies",
        default_get_build_backend_dependencies,
        ctx=ctx,
        req=req,
        sdist_root_dir=sdist_root_dir,
    )
    deps = _filter_requirements(req, orig_deps)

    _write_requirements_file(
        deps,
        build_backend_req_file,
    )
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

    build_sdist_req_file = sdist_root_dir.parent / "build-sdist-requirements.txt"
    if build_sdist_req_file.exists():
        logger.info(
            f"{req.name}: loading build sdist dependencies from {build_sdist_req_file.name}"
        )
        return _read_requirements_file(build_sdist_req_file)

    orig_deps = overrides.find_and_invoke(
        req.name,
        "get_build_sdist_dependencies",
        default_get_build_sdist_dependencies,
        ctx=ctx,
        req=req,
        sdist_root_dir=sdist_root_dir,
    )
    deps = _filter_requirements(req, orig_deps)

    _write_requirements_file(
        deps,
        build_sdist_req_file,
    )
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


def get_install_dependencies_of_wheel(
    req: Requirement, wheel_filename: pathlib.Path, requirements_file_dir: pathlib.Path
) -> set[Requirement]:
    logger.info(f"{req.name}: getting installation dependencies from {wheel_filename}")
    wheel = pkginfo.Wheel(wheel_filename)
    deps = _filter_requirements(req, wheel.requires_dist)
    _write_requirements_file(
        deps,
        requirements_file_dir / "requirements.txt",
    )
    return deps


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
            if requirements_file.evaluate_marker(req, r, req.extras):
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


def _write_requirements_file(
    requirements: typing.Iterable[Requirement],
    filename: pathlib.Path,
):
    with open(filename, "w") as f:
        for r in requirements:
            f.write(f"{r}\n")


def _read_requirements_file(
    filename: pathlib.Path,
) -> set[Requirement] | None:
    lines = requirements_file.parse_requirements_file(filename)
    return set([Requirement(line) for line in lines])
