import collections
import logging
import os
import pathlib
import platform
import shutil
import sys
import tempfile
import typing
import zipfile
from datetime import datetime

import elfdeps
import tomlkit
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

from . import context, external_commands, overrides

logger = logging.getLogger(__name__)


class BuildEnvironment:
    "Wrapper for a virtualenv used for build isolation."

    def __init__(
        self,
        ctx: context.WorkContext,
        parent_dir: pathlib.Path,
        build_requirements: typing.Iterable[Requirement] | None,
    ):
        self._ctx = ctx
        self.path = parent_dir / f"build-{platform.python_version()}"
        self._build_requirements = build_requirements
        self._createenv()

    @property
    def python(self) -> pathlib.Path:
        return (self.path / "bin/python3").absolute()

    def _createenv(self) -> None:
        if self.path.exists():
            logger.info("reusing build environment in %s", self.path)
            return

        logger.debug("creating build environment in %s", self.path)
        external_commands.run(
            [sys.executable, "-m", "virtualenv", str(self.path)],
            network_isolation=False,
        )
        logger.info("created build environment in %s", self.path)

        req_filename = self.path / "requirements.txt"
        # FIXME: Ensure each requirement is pinned to a specific version.
        with open(req_filename, "w") as f:
            if self._build_requirements:
                for r in self._build_requirements:
                    f.write(f"{r}\n")
        if not self._build_requirements:
            return
        external_commands.run(
            [
                str(self.python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--only-binary",
                ":all:",
            ]
            + self._ctx.pip_wheel_server_args
            + self._ctx.pip_constraint_args
            + [
                "-r",
                str(req_filename.absolute()),
            ],
            cwd=str(self.path.parent),
            network_isolation=False,
        )
        logger.info("installed dependencies into build environment in %s", self.path)


def analyze_wheel_elfdeps(
    ctx: context.WorkContext, req: Requirement, wheel: pathlib.Path
) -> tuple[set[elfdeps.SOInfo], set[elfdeps.SOInfo]] | tuple[None, None]:
    """Analyze a wheel's ELF dependencies

    Logs and returns library dependencies and library provides
    """
    _, _, _, tags = parse_wheel_filename(wheel.name)
    if all(tag.platform == "all" for tag in tags):
        logger.debug("%s: %s is a purelib wheel", req.name, wheel)
        return None, None

    # mapping of required libraries to list of versions
    requires: set[elfdeps.SOInfo] = set()
    provides: set[elfdeps.SOInfo] = set()

    settings = elfdeps.ELFAnalyzeSettings(filter_soname=True)
    with zipfile.ZipFile(wheel) as zf:
        for zipinfo in zf.infolist():
            if zipinfo.filename.endswith(".so"):
                info = elfdeps.analyze_zipmember(zf, zipinfo, settings=settings)
                provides.update(info.provides)
                requires.update(info.requires)

    # Don't show provided names as required names
    requires = requires.difference(provides)

    if requires:
        reqmap: dict[str, list[str]] = collections.defaultdict(list)
        for r in requires:
            reqmap[r.soname].append(r.version)

        names = sorted(
            name for name in reqmap if not name.startswith(("ld-linux", "rtld"))
        )
        logger.info("%s: Requires libraries: %s", req.name, ", ".join(names))
        for name, versions in sorted(reqmap.items()):
            logger.debug(
                "%s: Requires %s(%s)",
                req.name,
                name,
                ", ".join(v for v in versions if v),
            )

    if provides:
        names = sorted(p.soname for p in provides)
        logger.info("%s: Provides libraries: %s", req.name, ", ".join(names))

    return requires, provides


def add_extra_metadata_to_wheels(
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    extra_environ: dict[str, str],
    sdist_root_dir: pathlib.Path,
    wheel_file: pathlib.Path,
) -> pathlib.Path:
    # parse_wheel_filename normalizes the dist name, however the dist-info
    # directory uses the verbatim distribution name from the wheel file.
    # Packages with upper case names like "MarkupSafe" are affected.
    dist_name_normalized, dist_version, _, _ = parse_wheel_filename(wheel_file.name)
    dist_name = wheel_file.name.split("-", 1)[0]
    if dist_name_normalized != canonicalize_name(dist_name):
        # sanity check, should never fail
        raise ValueError(
            f"{req.name}: {dist_name_normalized} does not match {dist_name}"
        )
    dist_filename = f"{dist_name}-{dist_version}"

    extra_data_plugin = overrides.find_override_method(
        req.name, "add_extra_metadata_to_wheels"
    )
    data_to_add = {}
    if extra_data_plugin:
        data_to_add = overrides.invoke(
            extra_data_plugin,
            ctx=ctx,
            req=req,
            version=version,
            extra_environ=extra_environ,
            sdist_root_dir=sdist_root_dir,
        )
        if not isinstance(data_to_add, dict):
            logger.warning(
                f"{req.name}: unexpected return type from plugin add_extra_metadata_to_wheels. Expected dictionary. Will ignore"
            )
            data_to_add = {}

    with tempfile.TemporaryDirectory() as dir_name:
        cmd = ["wheel", "unpack", str(wheel_file), "--dest", dir_name]
        external_commands.run(
            cmd,
            cwd=dir_name,
            network_isolation=ctx.network_isolation,
        )

        dist_info_dir = (
            pathlib.Path(dir_name) / dist_filename / f"{dist_filename}.dist-info"
        )
        if not dist_info_dir.is_dir():
            raise ValueError(
                f"{req.name}: {wheel_file} does not contain {dist_info_dir.name}"
            )

        build_file = dist_info_dir / "fromager-build-settings"
        settings = ctx.settings.get_package_settings(req.name)
        if data_to_add:
            settings["metadata-from-plugin"] = data_to_add

        build_file.write_text(tomlkit.dumps(settings))

        req_files = sdist_root_dir.parent.glob("*-requirements.txt")
        for req_file in req_files:
            shutil.copy(req_file, dist_info_dir / f"fromager-{req_file.name}")

        build_tag_from_settings = ctx.settings.build_tag(req.name, version)
        build_tag = build_tag_from_settings if build_tag_from_settings else (0, "")

        cmd = [
            "wheel",
            "pack",
            str(dist_info_dir.parent),
            "--dest-dir",
            str(wheel_file.parent),
            "--build-number",
            f"{build_tag[0]}{build_tag[1]}",
        ]
        external_commands.run(
            cmd,
            cwd=dir_name,
            network_isolation=ctx.network_isolation,
        )

    wheel_file.unlink(missing_ok=True)
    wheels = list(wheel_file.parent.glob(f"{dist_filename}-*.whl"))
    if wheels:
        logger.info(
            f"{req.name}: added extra metadata and build tag {build_tag}, wheel renamed from {wheel_file.name} to {wheels[0].name}"
        )
        return wheels[0]
    raise FileNotFoundError("Could not locate new wheels file")


def build_wheel(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    version: Version,
    build_env: BuildEnvironment,
) -> pathlib.Path | None:
    logger.info(
        f"{req.name}: building wheel for {req} in {sdist_root_dir} writing to {ctx.wheels_build}"
    )
    extra_environ = overrides.extra_environ_for_pkg(ctx.envs_dir, req.name, ctx.variant)
    # TODO: refactor?
    # Build Rust without network access
    extra_environ["CARGO_NET_OFFLINE"] = "true"
    # configure max jobs settings. should cover most of the cases, if not then the user can use ctx.jobs in their plugin
    if ctx.jobs:
        extra_environ["MAKEFLAGS"] = (
            f"{extra_environ.get('MAKEFLAGS', '')} -j{ctx.jobs}"
        )
        extra_environ["CMAKE_BUILD_PARALLEL_LEVEL"] = f"{ctx.jobs}"
        extra_environ["MAX_JOBS"] = f"{ctx.jobs}"

    # Start the timer
    start = datetime.now().replace(microsecond=0)
    overrides.find_and_invoke(
        req.name,
        "build_wheel",
        default_build_wheel,
        ctx=ctx,
        build_env=build_env,
        extra_environ=extra_environ,
        req=req,
        sdist_root_dir=sdist_root_dir,
        build_dir=ctx.settings.build_dir(req.name, sdist_root_dir),
        version=version,
    )
    # End the timer
    end = datetime.now().replace(microsecond=0)
    wheels = list(ctx.wheels_build.glob("*.whl"))
    if len(wheels) != 1:
        raise FileNotFoundError("Could not locate built wheels")

    wheel = add_extra_metadata_to_wheels(
        ctx=ctx,
        req=req,
        version=version,
        extra_environ=extra_environ,
        sdist_root_dir=sdist_root_dir,
        wheel_file=wheels[0],
    )
    logger.info(f"{req.name}: built wheel '{wheel}' in {end - start}")
    analyze_wheel_elfdeps(ctx, req, wheel)
    return wheel


def default_build_wheel(
    ctx: context.WorkContext,
    build_env: BuildEnvironment,
    extra_environ: dict[str, typing.Any],
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    version: Version,
    build_dir: pathlib.Path,
) -> None:
    logger.debug(f"{req.name}: building wheel in {build_dir} with {extra_environ}")

    # Activate the virtualenv for the subprocess:
    # 1. Put the build environment at the front of the PATH to ensure
    #    any build tools are picked up from there and not global
    #    versions. If the caller has already set a path, start there.
    # 2. Set VIRTUAL_ENV so tools looking for that (for example,
    #    maturin) find it.
    existing_path = extra_environ.get("PATH") or os.environ.get("PATH") or ""
    path_parts = [str(build_env.python.parent)]
    if existing_path:
        path_parts.append(existing_path)
    updated_path = ":".join(path_parts)
    override_env = dict(os.environ)
    override_env.update(extra_environ)
    override_env["PATH"] = updated_path
    override_env["VIRTUAL_ENV"] = str(build_env.path)

    with tempfile.TemporaryDirectory() as dir_name:
        cmd = [
            os.fspath(build_env.python),
            "-m",
            "pip",
            "-vvv",
            "--disable-pip-version-check",
            "wheel",
            "--no-build-isolation",
            "--only-binary",
            ":all:",
            "--wheel-dir",
            os.fspath(ctx.wheels_build),
            "--no-deps",
            "--index-url",
            ctx.wheel_server_url,  # probably redundant, but just in case
            "--log",
            os.fspath(build_dir.parent / "build.log"),
            os.fspath(build_dir),
        ]
        external_commands.run(
            cmd,
            cwd=dir_name,
            extra_environ=override_env,
            network_isolation=ctx.network_isolation,
        )
