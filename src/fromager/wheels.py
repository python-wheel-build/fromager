from __future__ import annotations

import collections
import logging
import os
import pathlib
import shutil
import sys
import tempfile
import textwrap
import typing
import zipfile
from urllib.parse import unquote, urlparse

import elfdeps
import tomlkit
import wheel.wheelfile  # type: ignore
from packaging.requirements import Requirement
from packaging.tags import Tag
from packaging.utils import BuildTag, canonicalize_name, parse_wheel_filename
from packaging.version import Version

from . import (
    external_commands,
    metrics,
    overrides,
    requirements_file,
    resolver,
    sources,
)

if typing.TYPE_CHECKING:
    from . import build_environment, context

logger = logging.getLogger(__name__)

FROMAGER_BUILD_SETTINGS = "fromager-build-settings"
FROMAGER_ELF_PROVIDES = "fromager-elf-provides.txt"
FROMAGER_ELF_REQUIRES = "fromager-elf-requires.txt"
FROMAGER_BUILD_REQ_PREFIX = "fromager"


def _extra_metadata_elfdeps(
    ctx: context.WorkContext,
    req: Requirement,
    wheel_root_dir: pathlib.Path,
    dist_info_dir: pathlib.Path,
) -> typing.Iterable[elfdeps.ELFInfo]:
    """Analyze a wheel's ELF dependencies and add info files

    Logs and returns library dependencies and library provides. Writes
    requirements to dist-info.
    """
    # mapping of required libraries to list of versions
    requires: set[elfdeps.SOInfo] = set()
    provides: set[elfdeps.SOInfo] = set()
    elfinfos: list[elfdeps.ELFInfo] = []

    settings = elfdeps.ELFAnalyzeSettings(filter_soname=True)
    for info in elfdeps.analyze_dirtree(wheel_root_dir, settings=settings):
        if info.filename is not None:
            relname = str(info.filename.relative_to(wheel_root_dir))
        else:
            relname = "n/a"
        logger.debug(
            f"{relname} ({info.soname}) "
            f"requires {sorted(info.requires)}, "
            f"provides {sorted(info.provides)}"
        )
        provides.update(info.provides)
        requires.update(info.requires)
        elfinfos.append(info)

    # Don't list provided names as requirements
    requires = requires.difference(provides)

    if requires:
        reqmap: dict[str, list[str]] = collections.defaultdict(list)
        for r in requires:
            reqmap[r.soname].append(r.version)

        names = sorted(
            name for name in reqmap if not name.startswith(("ld-linux", "rtld"))
        )
        logger.info("Requires libraries: %s", ", ".join(names))
        for name, versions in sorted(reqmap.items()):
            logger.debug(
                "Requires %s(%s)",
                name,
                ", ".join(v for v in versions if v),
            )

        requires_file = dist_info_dir / FROMAGER_ELF_REQUIRES
        with requires_file.open("w", encoding="utf-8") as f:
            for soinfo in sorted(requires):
                f.write(f"{soinfo}\n")

    if provides:
        names = sorted(p.soname for p in provides)
        logger.info("Provides libraries: %s", ", ".join(names))

        provides_file = dist_info_dir / FROMAGER_ELF_PROVIDES
        with provides_file.open("w", encoding="utf-8") as f:
            for soinfo in sorted(provides):
                f.write(f"{soinfo}\n")

    return elfinfos


def extract_info_from_wheel_file(
    req: Requirement, wheel_file: pathlib.Path
) -> tuple[str, Version, BuildTag, frozenset[Tag]]:
    # parse_wheel_filename normalizes the dist name, however the dist-info
    # directory uses the verbatim distribution name from the wheel file.
    # Packages with upper case names like "MarkupSafe" are affected.
    dist_name_normalized, dist_version, build_tag, wheel_tags = parse_wheel_filename(
        wheel_file.name
    )
    dist_name = wheel_file.name.split("-", 1)[0]
    if dist_name_normalized != canonicalize_name(dist_name):
        # sanity check, should never fail
        raise ValueError(f"{dist_name_normalized} does not match {dist_name}")
    return (dist_name, dist_version, build_tag, wheel_tags)


def default_add_extra_metadata_to_wheels(
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    extra_environ: dict[str, str],
    sdist_root_dir: pathlib.Path,
    dist_info_dir: pathlib.Path,
) -> dict[str, typing.Any]:
    raise NotImplementedError


@metrics.timeit(description="add extra metadata to wheels")
def add_extra_metadata_to_wheels(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    extra_environ: dict[str, str],
    sdist_root_dir: pathlib.Path,
    wheel_file: pathlib.Path,
) -> pathlib.Path:
    pbi = ctx.package_build_info(req)
    dist_name, dist_version, _, wheel_tags = extract_info_from_wheel_file(
        req, wheel_file
    )
    dist_filename = f"{dist_name}-{dist_version}"

    extra_data_plugin = overrides.find_override_method(
        req.name, "add_extra_metadata_to_wheels"
    )
    data_to_add = {}

    with tempfile.TemporaryDirectory() as dir_name:
        wheel_root_dir = pathlib.Path(dir_name) / dist_filename
        wheel_root_dir.mkdir()
        with zipfile.ZipFile(str(wheel_file)) as zf:
            for infolist in zf.filelist:
                # Check for path traversal attempts
                if (
                    os.path.isabs(infolist.filename)
                    or ".." in pathlib.Path(infolist.filename).parts
                ):
                    raise ValueError(f"Unsafe path in wheel: {infolist.filename}")
                zf.extract(infolist, wheel_root_dir)
                # the higher 16 bits store the permissions and type of file (i.e. stat.filemode)
                # the lower bits of this give us the permission
                permissions = infolist.external_attr >> 16 & 0o777
                wheel_root_dir.joinpath(infolist.filename).chmod(permissions)

        dist_info_dir = wheel_root_dir / f"{dist_filename}.dist-info"
        if not dist_info_dir.is_dir():
            raise ValueError(f"{wheel_file} does not contain {dist_info_dir.name}")

        if extra_data_plugin:
            data_to_add = overrides.invoke(
                extra_data_plugin,
                ctx=ctx,
                req=req,
                version=version,
                extra_environ=extra_environ,
                sdist_root_dir=sdist_root_dir,
                dist_info_dir=dist_info_dir,
            )
            if not isinstance(data_to_add, dict):
                logger.warning(
                    "unexpected return type from plugin add_extra_metadata_to_wheels. Expected dictionary. Will ignore"
                )
                data_to_add = {}

        if pbi.has_config:
            settings = pbi.serialize(mode="json", exclude_defaults=False)
        else:
            settings = {}
        if data_to_add:
            settings["metadata-from-plugin"] = data_to_add
        build_file = dist_info_dir / FROMAGER_BUILD_SETTINGS
        build_file.write_text(tomlkit.dumps(settings))

        req_files = sdist_root_dir.parent.glob("*-requirements.txt")
        for req_file in req_files:
            shutil.copy(
                req_file, dist_info_dir / f"{FROMAGER_BUILD_REQ_PREFIX}-{req_file.name}"
            )

        if any(tag.platform != "all" for tag in wheel_tags):
            # platlib wheel
            if sys.platform == "linux":
                _extra_metadata_elfdeps(
                    ctx=ctx,
                    req=req,
                    wheel_root_dir=wheel_root_dir,
                    dist_info_dir=dist_info_dir,
                )
            else:
                logger.debug(
                    "shared library dependency analysis not implemented for %s",
                    sys.platform,
                )
        else:
            logger.debug("%s is a purelib wheel", req.name)

        build_tag_from_settings = pbi.build_tag(version)
        build_tag = build_tag_from_settings if build_tag_from_settings else (0, "")

        cmd = [
            "wheel",
            "pack",
            str(wheel_root_dir),
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
            f"added extra metadata and build tag {build_tag}, wheel renamed from {wheel_file.name} to {wheels[0].name}"
        )
        return wheels[0]
    raise FileNotFoundError("Could not locate new wheels file")


@metrics.timeit(description="build wheels")
def build_wheel(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    version: Version,
    build_env: build_environment.BuildEnvironment,
) -> pathlib.Path:
    pbi = ctx.package_build_info(req)
    logger.info(
        f"building {ctx.variant} wheel for {req} in {sdist_root_dir} "
        f"writing to {ctx.wheels_build}"
    )

    # add package and variant env vars, package's parallel job vars, and
    # build_env's virtual env vars.
    extra_environ = pbi.get_extra_environ(build_env=build_env)

    if (
        pbi.build_ext_parallel
        and "DIST_EXTRA_CONFIG" not in extra_environ
        and "MAX_JOBS" in extra_environ
    ):
        # configure setuptools to use parallel builds
        # https://setuptools.pypa.io/en/latest/deprecated/distutils/configfile.html
        dist_extra_cfg = build_env.path / "dist-extra.cfg"
        dist_extra_cfg.write_text(
            textwrap.dedent(
                f"""
                [build_ext]
                parallel = {extra_environ["MAX_JOBS"]}
                """
            )
        )
        extra_environ["DIST_EXTRA_CONFIG"] = str(dist_extra_cfg)

    overrides.find_and_invoke(
        req.name,
        "build_wheel",
        default_build_wheel,
        ctx=ctx,
        build_env=build_env,
        extra_environ=extra_environ,
        req=req,
        sdist_root_dir=sdist_root_dir,
        build_dir=pbi.build_dir(sdist_root_dir),
        version=version,
    )
    # End the timer
    wheels = list(ctx.wheels_build.glob("*.whl"))
    if len(wheels) != 1:
        raise FileNotFoundError(
            f"Expected 1 built wheel in {ctx.wheels_build}, got {len(wheels)}"
        )

    wheel = add_extra_metadata_to_wheels(
        ctx=ctx,
        req=req,
        version=version,
        extra_environ=extra_environ,
        sdist_root_dir=sdist_root_dir,
        wheel_file=wheels[0],
    )
    return wheel


def default_build_wheel(
    ctx: context.WorkContext,
    build_env: build_environment.BuildEnvironment,
    extra_environ: dict[str, str],
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    version: Version,
    build_dir: pathlib.Path,
) -> None:
    logger.debug(f"building wheel in {build_dir} with {extra_environ}")
    pbi = ctx.package_build_info(req)

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
    ]
    # config settings needs pip >= 24.0 to work. Fromager uses `virtualenv``
    # package to create virtual envs, which comes with recent pip. Stdlib's
    # `venv` comes with rather old pip.
    for key, values in pbi.config_settings.items():
        for value in values:
            cmd.append(f"--config-settings={key}={value}")
    cmd.append(os.fspath(build_dir))

    with tempfile.TemporaryDirectory() as dir_name:
        build_env.run(
            cmd,
            cwd=dir_name,
            extra_environ=extra_environ,
            network_isolation=ctx.network_isolation,
        )


def download_wheel(
    req: Requirement,
    wheel_url: str,
    output_directory: pathlib.Path,
) -> pathlib.Path:
    wheel_filename = output_directory / unquote(
        os.path.basename(urlparse(wheel_url).path)
    )
    if not wheel_filename.exists():
        logger.info(f"downloading pre-built wheel {wheel_url}")
        wheel_filename = _download_wheel_check(req, output_directory, wheel_url)
        logger.info(f"saved wheel to {wheel_filename}")
    else:
        logger.info(f"have existing wheel {wheel_filename}")

    return wheel_filename


def _download_wheel_check(
    req: Requirement, destination_dir: pathlib.Path, wheel_url: str
) -> pathlib.Path:
    wheel_filename = sources.download_url(
        req=req,
        destination_dir=destination_dir,
        url=wheel_url,
    )
    # validates whether the wheel is correct or not. will raise an error in the wheel is invalid
    wheel.wheelfile.WheelFile(wheel_filename)
    return wheel_filename


def get_wheel_server_urls(ctx: context.WorkContext, req: Requirement) -> list[str]:
    pbi = ctx.package_build_info(req)
    if pbi.wheel_server_url:
        # use only the wheel server from settings if it is defined. Do not fallback to other URLs
        servers = [pbi.wheel_server_url]
    else:
        servers = [resolver.PYPI_SERVER_URL]
        if ctx.wheel_server_url:
            servers.insert(0, ctx.wheel_server_url)
    return servers


@metrics.timeit(description="resolve wheel")
def resolve_prebuilt_wheel(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    wheel_server_urls: list[str],
    req_type: requirements_file.RequirementType | None = None,
) -> tuple[str, Version]:
    "Return URL to wheel and its version."
    for url in wheel_server_urls:
        try:
            wheel_url, resolved_version = resolver.resolve(
                ctx=ctx,
                req=req,
                sdist_server_url=url,
                include_sdists=False,
                include_wheels=True,
                req_type=req_type,
                # pre-built wheels must match platform
                ignore_platform=False,
            )
        except Exception:
            continue
        if wheel_url and resolved_version:
            return (wheel_url, resolved_version)
    raise ValueError(
        f"Could not find a prebuilt wheel for {req} on {' or '.join(wheel_server_urls)}"
    )
