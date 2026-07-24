from __future__ import annotations

import logging
import os
import pathlib
import typing
import zipfile
from urllib.parse import urlparse

import requests.exceptions
from packaging.requirements import Requirement
from packaging.version import Version
from resolvelib.resolvers import ResolverException

from .. import dependencies, finders, resolver, server, wheels
from ..requirements_file import RequirementType
from ._types import PreparedSourceData

if typing.TYPE_CHECKING:
    from .. import context

logger = logging.getLogger(__name__)


def _create_unpack_dir(
    work_dir: pathlib.Path,
    req: Requirement,
    resolved_version: Version,
) -> pathlib.Path:
    unpack_dir = work_dir / f"{req.name}-{resolved_version}"
    unpack_dir.mkdir(parents=True, exist_ok=True)
    return unpack_dir


def _extract_build_reqs_from_wheel(
    work_dir: pathlib.Path,
    req: Requirement,
    resolved_version: Version,
    wheel_filename: pathlib.Path,
) -> pathlib.Path | None:
    """Extract fromager build requirement files from a wheel archive.

    Looks for files prefixed with `FROMAGER_BUILD_REQ_PREFIX` inside the
    wheel's `.dist-info` directory and extracts them to a local unpack
    directory. Returns the unpack directory on success, or None if the
    files are not present or extraction fails.
    """
    dist_name, dist_version, _, _ = wheels.extract_info_from_wheel_file(
        req, wheel_filename
    )
    unpack_dir = _create_unpack_dir(work_dir, req, resolved_version)
    dist_filename = f"{dist_name}-{dist_version}"
    dist_info_path = pathlib.Path(f"{dist_filename}.dist-info")
    req_filenames: list[str] = [
        dependencies.BUILD_BACKEND_REQ_FILE_NAME,
        dependencies.BUILD_SDIST_REQ_FILE_NAME,
        dependencies.BUILD_SYSTEM_REQ_FILE_NAME,
    ]
    try:
        with zipfile.ZipFile(wheel_filename) as archive:
            for filename in req_filenames:
                zipinfo = archive.getinfo(
                    str(
                        dist_info_path
                        / f"{wheels.FROMAGER_BUILD_REQ_PREFIX}-{filename}"
                    )
                )
                if os.path.isabs(zipinfo.filename) or ".." in zipinfo.filename:
                    raise ValueError(f"Unsafe path in wheel: {zipinfo.filename}")
                zipinfo.filename = filename
                output_file = archive.extract(zipinfo, unpack_dir)
                logger.info(f"extracted {output_file}")
        logger.info(f"extracted build requirements from wheel into {unpack_dir}")
        return unpack_dir
    except Exception as e:
        logger.info(f"could not extract build requirements from wheel: {e}")
        for filename in req_filenames:
            unpack_dir.joinpath(filename).unlink(missing_ok=True)
        return None


def _look_for_existing_wheel(
    ctx: context.WorkContext,
    req: Requirement,
    resolved_version: Version,
    search_in: pathlib.Path,
) -> tuple[pathlib.Path | None, pathlib.Path | None]:
    pbi = ctx.package_build_info(req)
    expected_build_tag = pbi.build_tag(resolved_version)
    logger.info(
        f"looking for existing wheel for version {resolved_version} with build tag {expected_build_tag} in {search_in}"
    )
    wheel_filename = finders.find_wheel(
        downloads_dir=search_in,
        req=req,
        dist_version=str(resolved_version),
        build_tag=expected_build_tag,
    )
    if not wheel_filename:
        return None, None
    _, _, build_tag, _ = wheels.extract_info_from_wheel_file(req, wheel_filename)
    if expected_build_tag and expected_build_tag != build_tag:
        logger.info(
            f"found wheel for {resolved_version} in {wheel_filename} but build tag does not match. Got {build_tag} but expected {expected_build_tag}"
        )
        return None, None
    logger.info(f"found existing wheel {wheel_filename}")
    build_reqs_dir = _extract_build_reqs_from_wheel(
        ctx.work_dir, req, resolved_version, wheel_filename
    )
    return wheel_filename, build_reqs_dir


def _download_wheel_from_cache(
    ctx: context.WorkContext,
    cache_wheel_server_url: str | None,
    req: Requirement,
    resolved_version: Version,
) -> tuple[pathlib.Path | None, pathlib.Path | None]:
    if not cache_wheel_server_url:
        return None, None
    logger.info(f"checking if wheel was already uploaded to {cache_wheel_server_url}")
    try:
        pinned_req = Requirement(f"{req.name}=={resolved_version}")
        provider = finders.PyPICacheProvider(
            cache_server_url=cache_wheel_server_url,
            constraints=ctx.constraints,
        )
        results = resolver.find_all_matching_from_provider(provider, pinned_req)
        wheel_url, _ = results[0]
        wheelfile_name = pathlib.Path(urlparse(wheel_url).path)
        pbi = ctx.package_build_info(req)
        expected_build_tag = pbi.build_tag(resolved_version)
        logger.info(f"has expected build tag {expected_build_tag}")
        changelogs = pbi.get_changelog(resolved_version)
        logger.debug(f"has change logs {changelogs}")

        _, _, build_tag, _ = wheels.extract_info_from_wheel_file(req, wheelfile_name)
        if expected_build_tag and expected_build_tag != build_tag:
            logger.info(
                f"found wheel for {resolved_version} in cache but build tag does not match. Got {build_tag} but expected {expected_build_tag}"
            )
            return None, None

        cached_wheel = wheels.download_wheel(
            req=req, wheel_url=wheel_url, output_directory=ctx.wheels_downloads
        )
        if cache_wheel_server_url != ctx.wheel_server_url:
            server.update_wheel_mirror(ctx)
        logger.info("found built wheel on cache server")
        unpack_dir = _extract_build_reqs_from_wheel(
            ctx.work_dir, req, resolved_version, cached_wheel
        )
        return cached_wheel, unpack_dir
    except ResolverException:
        logger.info(
            f"did not find wheel for {resolved_version} in {cache_wheel_server_url}"
        )
        return None, None
    except requests.exceptions.RequestException as err:
        logger.warning(
            f"network error checking wheel cache for {resolved_version} "
            f"at {cache_wheel_server_url}: {err}"
        )
        return None, None
    except Exception as err:
        logger.warning(
            f"unexpected error checking wheel cache for {resolved_version} "
            f"at {cache_wheel_server_url}: {err}"
        )
        return None, None


def find_cached_wheel(
    ctx: context.WorkContext,
    cache_wheel_server_url: str | None,
    req: Requirement,
    resolved_version: Version,
) -> tuple[pathlib.Path | None, pathlib.Path | None]:
    """Look for cached wheel in 3 locations (thread-safe, no Bootstrapper state).

    Checks for cached wheels in order:
    1. wheels_build directory (previously built)
    2. wheels_downloads directory (previously downloaded)
    3. Cache server (remote cache)

    Returns:
        Tuple of (cached_wheel_filename, unpacked_cached_wheel).
        Both None if no cache hit.
    """
    cached_wheel, unpacked = _look_for_existing_wheel(
        ctx, req, resolved_version, ctx.wheels_build
    )
    if cached_wheel:
        return cached_wheel, unpacked

    cached_wheel, unpacked = _look_for_existing_wheel(
        ctx, req, resolved_version, ctx.wheels_downloads
    )
    if cached_wheel:
        return cached_wheel, unpacked

    cached_wheel, unpacked = _download_wheel_from_cache(
        ctx, cache_wheel_server_url, req, resolved_version
    )
    if cached_wheel:
        return cached_wheel, unpacked

    return None, None


def bg_prepare_prebuilt(
    ctx: context.WorkContext,
    req: Requirement,
    req_type: RequirementType,
    resolved_version: Version,
    wheel_url: str,
) -> PreparedSourceData:
    """Background-safe prebuilt download: no Bootstrapper state accessed."""
    # Thread-safe: paths include {req.name}-{resolved_version} (unique per package),
    # mkdir uses exist_ok=True (atomic), and update_wheel_mirror() is already locked.
    logger.info(f"using pre-built wheel for {req_type} requirement")
    wheel_filename = wheels.download_wheel(req, wheel_url, ctx.wheels_prebuilt)
    unpack_dir = _create_unpack_dir(ctx.work_dir, req, resolved_version)
    server.update_wheel_mirror(ctx)
    return PreparedSourceData(wheel_filename=wheel_filename, unpack_dir=unpack_dir)
