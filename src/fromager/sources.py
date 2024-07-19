import inspect
import json
import logging
import os.path
import pathlib
import shutil
import string
import subprocess
import tarfile
import typing
import zipfile
from urllib.parse import urlparse

import requests
import resolvelib
from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version
from packaging.version import parse as validate_version

from . import context, dependencies, overrides, resolver, tarballs, vendor_rust, wheels

logger = logging.getLogger(__name__)

PYPI_SERVER_URL = "https://pypi.org/simple"
GITHUB_URL = "https://github.com"
DEFAULT_SDIST_SERVER_URLS = [
    PYPI_SERVER_URL,
]


def download_source(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_server_urls: list[str],
) -> tuple[pathlib.Path, str, str, str]:
    downloader = overrides.find_override_method(req.name, "download_source")
    source_type = "override"
    if not downloader:
        downloader = default_download_source
        source_type = "sdist"
    for url in sdist_server_urls:
        try:
            logger.debug(
                f"{req.name}: trying to resolve and download {req} using {url}"
            )
            download_details = overrides.invoke(
                downloader,
                ctx=ctx,
                req=req,
                sdist_server_url=url,
            )
            if len(download_details) == 3:
                source_filename, version, source_url = download_details
            elif len(download_details) == 2:
                source_filename, version = download_details
                source_url = "override"
            else:
                raise ValueError(
                    f"do not know how to unpack {download_details}, expected 2 or 3 members"
                )

            # Validate version string by passing it to parse
            validate_version(str(version))

        except (
            resolvelib.InconsistentCandidate,
            resolvelib.RequirementsConflicted,
            resolvelib.ResolutionImpossible,
            InvalidVersion,
        ) as err:
            logger.debug(f"{req.name}: failed to resolve {req} using {url}: {err}")
            continue

        return (source_filename, version, source_url, source_type)
    servers = ", ".join(sdist_server_urls)
    raise ValueError(f"failed to find source for {req} at {servers}")


def resolve_dist(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_server_url: str,
    include_sdists: bool = True,
    include_wheels: bool = True,
) -> tuple[str, str]:
    "Return URL to source and its version."
    constraint = ctx.constraints.get_constraint(req)
    logger.debug(
        f"{req.name}: resolving requirement {req} using {sdist_server_url} with constraint {constraint}"
    )

    # Create the (reusable) resolver. Limit to sdists.
    provider = overrides.find_and_invoke(
        req.name,
        "get_resolver_provider",
        default_resolver_provider,
        ctx=ctx,
        req=req,
        include_sdists=include_sdists,
        include_wheels=include_wheels,
        sdist_server_url=sdist_server_url,
    )

    reporter = resolvelib.BaseReporter()
    rslvr = resolvelib.Resolver(provider, reporter)

    # Kick off the resolution process, and get the final result.
    try:
        result = rslvr.resolve([req])
    except (
        resolvelib.InconsistentCandidate,
        resolvelib.RequirementsConflicted,
        resolvelib.ResolutionImpossible,
    ) as err:
        logger.debug(f"{req.name}: could not resolve {req} with {constraint}: {err}")
        raise

    for candidate in result.mapping.values():
        return (candidate.url, candidate.version)
    return (None, None)


def default_resolver_provider(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_server_url: str,
    include_sdists: bool,
    include_wheels: bool,
) -> resolver.PyPIProvider:
    return resolver.PyPIProvider(
        include_sdists=include_sdists,
        include_wheels=include_wheels,
        sdist_server_url=sdist_server_url,
        constraints=ctx.constraints,
    )


def default_download_source(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_server_url: str,
) -> tuple[pathlib.Path, str, str]:
    "Download the requirement and return the name of the output path."
    url_template = ctx.settings.sdist_download_url(req.name)
    rename_to_template = ctx.settings.sdist_local_filename(req.name)

    # don't include sdists if the user wants to download source from a predefined url
    include_sdists = url_template is None
    include_wheels = not include_sdists

    org_url, version = resolve_dist(
        ctx, req, sdist_server_url, include_sdists, include_wheels
    )

    url = _resolve_template(url_template, req, version) or org_url
    logger.debug(f"{req.name}: using {url} instead of {org_url}")

    rename_to = _resolve_template(rename_to_template, req, version)

    source_filename = _download_source_check(ctx.sdists_downloads, url, rename_to)
    logger.debug(
        f"{req.name}: have source for {req} version {version} in {source_filename}"
    )
    return (source_filename, version, url)


# Helper method to check whether .zip /.tar / .tgz is able to extract and check its content.
# It will throw exception if any other file is encountered. Eg: index.html
def _download_source_check(
    destination_dir: pathlib.Path, url: str, rename_to: str | None = None
) -> str:
    source_filename = download_url(destination_dir, url, rename_to)
    if source_filename.suffix == ".zip":
        source_file_contents = zipfile.ZipFile(source_filename).namelist()
        if not source_file_contents:
            raise zipfile.BadZipFile(f"Empty zip file encountered: {source_filename}")
    elif source_filename.suffix == ".tgz" or source_filename.suffix == ".gz":
        with tarfile.open(source_filename) as tar:
            contents = tar.getnames()
            if not contents:
                raise TypeError(f"Empty tar file encountered: {source_filename}")
    else:
        raise TypeError(
            f"The source file encountered is not a zip or tar file: {source_filename}"
        )
    return source_filename


def download_url(
    destination_dir: pathlib.Path, url: str, rename_to: str | None = None
) -> pathlib.Path:
    basename = rename_to if rename_to else os.path.basename(urlparse(url).path)
    outfile = pathlib.Path(destination_dir) / basename
    logger.debug(
        "looking for %s %s", outfile, "(exists)" if outfile.exists() else "(not there)"
    )
    if outfile.exists():
        logger.debug(f"already have {outfile}")
        return outfile
    # Open the URL first in case that fails, so we don't end up with an empty file.
    logger.debug(f"reading from {url}")
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(outfile, "wb") as f:
            logger.debug(f"writing to {outfile}")
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
    logger.info(f"saved {outfile}")
    return outfile


def _resolve_template(template: str | None, req: Requirement, version: str):
    if not template:
        return None
    template_env = {"version": version}
    try:
        return string.Template(template).substitute(template_env)
    except KeyError:
        logger.warning(
            f"{req.name}: Couldn't resolve url or name for {req} using the template: {template_env}"
        )
        raise


def _sdist_root_name(source_filename: pathlib.Path) -> str:
    base_name = pathlib.Path(source_filename).name
    if base_name.endswith(".tar.gz"):
        ext_to_strip = ".tar.gz"
    elif base_name.endswith(".zip"):
        ext_to_strip = ".zip"
    else:
        raise ValueError(f"Do not know how to work with {source_filename}")
    return base_name[: -len(ext_to_strip)]


def _takes_arg(f: typing.Callable, arg_name: str) -> bool:
    sig = inspect.signature(f)
    return arg_name in sig.parameters


def unpack_source(
    ctx: context.WorkContext,
    source_filename: pathlib.Path,
) -> tuple[pathlib.Path, bool]:
    unpack_dir = ctx.work_dir / _sdist_root_name(source_filename)
    if unpack_dir.exists():
        if ctx.cleanup:
            logger.debug("cleaning up %s", unpack_dir)
            shutil.rmtree(unpack_dir)
        else:
            logger.info("reusing %s", unpack_dir)
            return (unpack_dir / unpack_dir.name, False)
    # We create a unique directory based on the sdist name, but that
    # may not be the same name as the root directory of the content in
    # the sdist (due to case, punctuation, etc.), so after we unpack
    # it look for what was created.
    logger.debug("unpacking %s to %s", source_filename, unpack_dir)
    if str(source_filename).endswith(".tar.gz"):
        with tarfile.open(source_filename, "r") as t:
            if _takes_arg(t.extractall, "filter"):
                t.extractall(unpack_dir, filter="data")
            else:
                logger.debug('unpacking without filter="data"')
                t.extractall(unpack_dir)
    elif str(source_filename).endswith(".zip"):
        with zipfile.ZipFile(source_filename) as zf:
            zf.extractall(path=unpack_dir)
    else:
        raise ValueError(f"Do not know how to unpack source archive {source_filename}")
    return (next(iter(unpack_dir.glob("*"))), True)


def patch_source(ctx: context.WorkContext, source_root_dir: pathlib.Path) -> None:
    for p in overrides.patches_for_source_dir(ctx.patches_dir, source_root_dir.name):
        logger.info("applying patch file %s to %s", p, source_root_dir)
        with open(p, "r") as f:
            subprocess.check_call(
                ["patch", "-p1"],
                stdin=f,
                cwd=source_root_dir,
            )


def write_build_meta(
    unpack_dir: pathlib.Path,
    req: Requirement,
    source_filename: pathlib.Path,
    version: Version,
) -> pathlib.Path:
    meta_file = unpack_dir / "build-meta.json"
    with open(meta_file, "w") as f:
        json.dump(
            {
                "req": str(req),
                "source-filename": str(source_filename),
                "version": str(version),
            },
            f,
        )
    logger.debug("wrote build metadata to %s", meta_file)
    return meta_file


def read_build_meta(unpack_dir: pathlib.Path) -> dict:
    meta_file = unpack_dir / "build-meta.json"
    with open(meta_file, "r") as f:
        return json.load(f)


def prepare_source(
    ctx: context.WorkContext,
    req: Requirement,
    source_filename: pathlib.Path,
    version: Version,
) -> pathlib.Path:
    logger.info(f"{req.name}: preparing source for {req} from {source_filename}")
    source_root_dir = overrides.find_and_invoke(
        req.name,
        "prepare_source",
        _default_prepare_source,
        ctx=ctx,
        req=req,
        source_filename=source_filename,
        version=version,
    )
    write_build_meta(source_root_dir.parent, req, source_filename, version)
    if source_root_dir is not None:
        logger.info(f"{req.name}: prepared source for {req} at {source_root_dir}")
    return source_root_dir


def _default_prepare_source(
    ctx: context.WorkContext,
    req: Requirement,
    source_filename: pathlib.Path,
    version: Version,
) -> pathlib.Path:
    source_root_dir, is_new = unpack_source(ctx, source_filename)
    if is_new:
        patch_source(ctx, source_root_dir)
        vendor_rust.vendor_rust(req, source_root_dir)
    return source_root_dir


def build_sdist(
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    sdist_root_dir: pathlib.Path,
    build_env: wheels.BuildEnvironment,
) -> pathlib.Path:
    logger.info(f"{req.name}: building source distribution in {sdist_root_dir}")
    extra_environ = overrides.extra_environ_for_pkg(ctx.envs_dir, req.name, ctx.variant)
    sdist_filename = overrides.find_and_invoke(
        req.name,
        "build_sdist",
        default_build_sdist,
        ctx=ctx,
        extra_environ=extra_environ,
        req=req,
        version=version,
        sdist_root_dir=sdist_root_dir,
        build_env=build_env,
    )
    logger.info(f"{req.name}: built source distribution {sdist_filename}")
    return sdist_filename


def default_build_sdist(
    ctx: context.WorkContext,
    extra_environ: dict,
    req: Requirement,
    version: Version,
    sdist_root_dir: pathlib.Path,
    build_env: wheels.BuildEnvironment,
) -> pathlib.Path:
    # It seems like the "correct" way to do this would be to run the
    # PEP 517 API in the source tree we have modified. However, quite
    # a few packages assume their source distribution is being built
    # from a source code repository checkout and those throw an error
    # when we use the interface to try to rebuild the sdist. Since we
    # know what we have is an exploded tarball, we just tar it back
    # up.
    #
    # For cases where the PEP 517 approach works, use
    # pep517_build_sdist().
    sdist_filename = ctx.sdists_builds / (sdist_root_dir.name + ".tar.gz")
    if sdist_filename.exists():
        sdist_filename.unlink()
    # The format argument is specified based on
    # https://peps.python.org/pep-0517/#build-sdist.
    with tarfile.open(sdist_filename, "x:gz", format=tarfile.PAX_FORMAT) as sdist:
        tarballs.tar_reproducible(sdist, sdist_root_dir)
    return sdist_filename


def pep517_build_sdist(
    ctx: context.WorkContext,
    extra_environ: dict,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    version: Version,
) -> pathlib.Path:
    """Use the PEP 517 API to build a source distribution from a modified source tree."""
    pyproject_toml = dependencies.get_pyproject_contents(sdist_root_dir)
    hook_caller = dependencies.get_build_backend_hook_caller(
        sdist_root_dir, pyproject_toml, extra_environ
    )
    sdist_filename = hook_caller.build_sdist(ctx.sdists_builds)
    return sdist_filename
