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
from datetime import datetime
from urllib.parse import urlparse

import elfdeps
import tomlkit
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

from . import (
    build_environment,
    context,
    external_commands,
    overrides,
    resolver,
    sources,
)

logger = logging.getLogger(__name__)

FROMAGER_BUILD_SETTINGS = "fromager-build-settings"
FROMAGER_ELF_PROVIDES = "fromager-elf-provides.txt"
FROMAGER_ELF_REQUIRES = "fromager-elf-requires.txt"


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
            f"{req.name}: {relname} ({info.soname}) "
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
        logger.info("%s: Requires libraries: %s", req.name, ", ".join(names))
        for name, versions in sorted(reqmap.items()):
            logger.debug(
                "%s: Requires %s(%s)",
                req.name,
                name,
                ", ".join(v for v in versions if v),
            )

        requires_file = dist_info_dir / FROMAGER_ELF_REQUIRES
        with requires_file.open("w", encoding="utf-8") as f:
            for soinfo in sorted(requires):
                f.write(f"{soinfo}\n")

    if provides:
        names = sorted(p.soname for p in provides)
        logger.info("%s: Provides libraries: %s", req.name, ", ".join(names))

        provides_file = dist_info_dir / FROMAGER_ELF_REQUIRES
        with provides_file.open("w", encoding="utf-8") as f:
            for soinfo in sorted(provides):
                f.write(f"{soinfo}\n")

    return elfinfos


def default_add_extra_metadata_to_wheels(
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    extra_environ: dict[str, str],
    sdist_root_dir: pathlib.Path,
    dist_info_dir: pathlib.Path,
) -> dict[str, typing.Any]:
    raise NotImplementedError


def add_extra_metadata_to_wheels(
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    extra_environ: dict[str, str],
    sdist_root_dir: pathlib.Path,
    wheel_file: pathlib.Path,
) -> pathlib.Path:
    pbi = ctx.package_build_info(req)
    # parse_wheel_filename normalizes the dist name, however the dist-info
    # directory uses the verbatim distribution name from the wheel file.
    # Packages with upper case names like "MarkupSafe" are affected.
    dist_name_normalized, dist_version, _, wheel_tags = parse_wheel_filename(
        wheel_file.name
    )
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

    with tempfile.TemporaryDirectory() as dir_name:
        cmd = ["wheel", "unpack", str(wheel_file), "--dest", dir_name]
        external_commands.run(
            cmd,
            cwd=dir_name,
            network_isolation=ctx.network_isolation,
        )

        wheel_root_dir = pathlib.Path(dir_name) / dist_filename
        dist_info_dir = wheel_root_dir / f"{dist_filename}.dist-info"
        if not dist_info_dir.is_dir():
            raise ValueError(
                f"{req.name}: {wheel_file} does not contain {dist_info_dir.name}"
            )

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
                    f"{req.name}: unexpected return type from plugin add_extra_metadata_to_wheels. Expected dictionary. Will ignore"
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
            shutil.copy(req_file, dist_info_dir / f"fromager-{req_file.name}")

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
                    "%s: shared library dependency analysis not implemented for %s",
                    req.name,
                    sys.platform,
                )
        else:
            logger.debug("%s: is a purelib wheel", req.name)

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
            f"{req.name}: added extra metadata and build tag {build_tag}, wheel renamed from {wheel_file.name} to {wheels[0].name}"
        )
        return wheels[0]
    raise FileNotFoundError("Could not locate new wheels file")


def build_wheel(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    version: Version,
    build_env: build_environment.BuildEnvironment,
) -> pathlib.Path | None:
    pbi = ctx.package_build_info(req)
    logger.info(
        f"{req.name}: building wheel for {req} in {sdist_root_dir} writing to {ctx.wheels_build}"
    )

    extra_environ: dict[str, str] = {}
    # TODO: refactor?
    # Build Rust without network access
    extra_environ["CARGO_NET_OFFLINE"] = "true"
    # configure max jobs settings, settings depend on package, available
    # CPU cores, and available virtual memory.
    jobs = pbi.parallel_jobs()
    extra_environ["MAKEFLAGS"] = f"{extra_environ.get('MAKEFLAGS', '')} -j{jobs}"
    extra_environ["CMAKE_BUILD_PARALLEL_LEVEL"] = str(jobs)
    extra_environ["MAX_JOBS"] = str(jobs)

    if pbi.build_ext_parallel:
        # configure setuptools to use parallel builds
        # https://setuptools.pypa.io/en/latest/deprecated/distutils/configfile.html
        dist_extra_cfg = build_env.path / "dist-extra.cfg"
        dist_extra_cfg.write_text(
            textwrap.dedent(
                f"""
                [build_ext]
                parallel = {jobs}
                """
            )
        )
        extra_environ["DIST_EXTRA_CONFIG"] = str(dist_extra_cfg)

    # add package and variant env vars last
    template_env = os.environ.copy()
    template_env.update(extra_environ)
    extra_environ.update(pbi.get_extra_environ(template_env=template_env))

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
        build_dir=pbi.build_dir(sdist_root_dir),
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
    return wheel


def default_build_wheel(
    ctx: context.WorkContext,
    build_env: build_environment.BuildEnvironment,
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


def download_wheel(
    req: Requirement,
    wheel_url: str,
    output_directory: pathlib.Path,
) -> pathlib.Path:
    wheel_filename = output_directory / os.path.basename(urlparse(wheel_url).path)
    if not wheel_filename.exists():
        logger.info(f"{req.name}: downloading pre-built wheel {wheel_url}")
        wheel_filename = _download_wheel_check(output_directory, wheel_url)
        logger.info(f"{req.name}: saved wheel to {wheel_filename}")
    else:
        logger.info(f"{req.name}: have existing wheel {wheel_filename}")

    return wheel_filename


# Helper method to check whether the .whl file is a zip file and has contents in it.
# It will throw BadZipFile exception if any other file is encountered. Eg: index.html
def _download_wheel_check(destination_dir, wheel_url):
    wheel_filename = sources.download_url(destination_dir, wheel_url)
    wheel_directory_contents = zipfile.ZipFile(wheel_filename).namelist()
    if not wheel_directory_contents:
        raise zipfile.BadZipFile(f"Empty zip file encountered: {wheel_filename}")

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


def resolve_prebuilt_wheel(
    ctx: context.WorkContext,
    req: Requirement,
    wheel_server_urls: list[str],
) -> tuple[str, Version]:
    "Return URL to wheel and its version."
    for url in wheel_server_urls:
        try:
            wheel_url, resolved_version = resolver.resolve(
                ctx,
                req,
                url,
                include_sdists=False,
                include_wheels=True,
            )
        except Exception:
            continue
        if wheel_url and resolved_version:
            return (wheel_url, resolved_version)
    raise ValueError(
        f'Could not find a prebuilt wheel for {req} on {" or ".join(wheel_server_urls)}'
    )
