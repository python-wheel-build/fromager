import inspect
import json
import logging
import os.path
import pathlib
import shutil
import tarfile
import typing
import zipfile
from urllib.parse import urlparse

import resolvelib
from packaging.requirements import Requirement
from packaging.version import Version

from . import (
    build_environment,
    context,
    dependencies,
    external_commands,
    overrides,
    pyproject,
    resolver,
    tarballs,
    vendor_rust,
)
from .request_session import session

logger = logging.getLogger(__name__)


def get_source_type(ctx: context.WorkContext, req: Requirement) -> str:
    source_type = "sdist"
    pbi = ctx.package_build_info(req)
    if (
        overrides.find_override_method(req.name, "download_source")
        or overrides.find_override_method(req.name, "resolve_source")
        or pbi.download_source_url(resolve_template=False)
    ):
        source_type = "override"
    return source_type


def download_source(
    ctx: context.WorkContext, req: Requirement, version: Version, download_url: str
) -> pathlib.Path:
    source_path = overrides.find_and_invoke(
        req.name,
        "download_source",
        default_download_source,
        ctx=ctx,
        req=req,
        version=version,
        download_url=download_url,
        sdists_downloads_dir=ctx.sdists_downloads,
    )

    if not isinstance(source_path, pathlib.Path):
        raise ValueError(
            f"expected a Path back to downloaded source. got {source_path}"
        )
    return source_path


def resolve_source(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_server_url: str,
) -> tuple[str, Version]:
    "Return URL to source and its version."
    constraint = ctx.constraints.get_constraint(req.name)
    logger.debug(
        f"{req.name}: resolving requirement {req} using {sdist_server_url} with constraint {constraint}"
    )

    try:
        resolver_results = overrides.find_and_invoke(
            req.name,
            "resolve_source",
            default_resolve_source,
            ctx=ctx,
            req=req,
            sdist_server_url=sdist_server_url,
        )
    except (
        resolvelib.InconsistentCandidate,
        resolvelib.RequirementsConflicted,
        resolvelib.ResolutionImpossible,
    ) as err:
        logger.debug(f"{req.name}: could not resolve {req} with {constraint}: {err}")
        raise

    if len(resolver_results) == 2:
        url, version = resolver_results
    else:
        raise ValueError(
            f"do not know how to unpack {resolver_results}, expected 2 members"
        )

    if not isinstance(version, Version):
        raise ValueError(f"expected 2nd member to be of type Version, got {version}")

    return str(url), version


def default_resolve_source(
    ctx: context.WorkContext, req: Requirement, sdist_server_url: str
) -> tuple[str, Version]:
    "Return URL to source and its version."

    pbi = ctx.package_build_info(req)
    override_sdist_server_url = pbi.resolver_sdist_server_url(sdist_server_url)

    url, version = resolver.resolve(
        ctx=ctx,
        req=req,
        sdist_server_url=override_sdist_server_url,
        include_sdists=pbi.resolver_include_sdists,
        include_wheels=pbi.resolver_include_wheels,
    )
    return url, version


def default_download_source(
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    download_url: str,
    sdists_downloads_dir: pathlib.Path,
) -> pathlib.Path:
    "Download the requirement and return the name of the output path."
    pbi = ctx.package_build_info(req)
    destination_filename = pbi.download_source_destination_filename(version=version)
    url = pbi.download_source_url(version=version, default=download_url)
    source_filename = _download_source_check(
        sdists_downloads_dir, url, destination_filename
    )

    logger.debug(
        f"{req.name}: have source for {req} version {version} in {source_filename}"
    )
    return source_filename


# Helper method to check whether .zip /.tar / .tgz is able to extract and check its content.
# It will throw exception if any other file is encountered. Eg: index.html
def _download_source_check(
    destination_dir: pathlib.Path,
    url: str,
    destination_filename: str | None = None,
) -> str:
    source_filename = download_url(destination_dir, url, destination_filename)
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
    destination_dir: pathlib.Path,
    url: str,
    destination_filename: str | None = None,
) -> pathlib.Path:
    basename = (
        destination_filename
        if destination_filename
        else os.path.basename(urlparse(url).path)
    )
    outfile = pathlib.Path(destination_dir) / basename
    logger.debug(
        "looking for %s %s", outfile, "(exists)" if outfile.exists() else "(not there)"
    )
    if outfile.exists():
        logger.debug(f"already have {outfile}")
        return outfile
    # Open the URL first in case that fails, so we don't end up with an empty file.
    logger.debug(f"reading from {url}")
    with session.get(url, stream=True) as r:
        r.raise_for_status()
        with open(outfile, "wb") as f:
            logger.debug(f"writing to {outfile}")
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
    logger.info(f"saved {outfile}")
    return outfile


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
    req: Requirement,
    version: Version,
    source_filename: pathlib.Path,
) -> tuple[pathlib.Path, bool]:
    # sdist names are less standardized and the names of the directories they
    # contain are also not very standard. Force the names into a predictable
    # form based on the override module name for the requirement.
    req_name = overrides.pkgname_to_override_module(req.name)
    expected_name = f"{req_name}-{version}"

    # The unpack_dir is a parent dir where we put temporary outputs during the
    # build process, including the unpacked source in a subdirectory.
    unpack_dir = ctx.work_dir / expected_name
    if unpack_dir.exists():
        if ctx.cleanup:
            logger.debug("cleaning up %s", unpack_dir)
            shutil.rmtree(unpack_dir)
        else:
            logger.info("reusing %s", unpack_dir)
            return (unpack_dir / unpack_dir.name, False)

    # sdists might be tarballs or zip files.
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

    # We create a unique directory based on the requirement name, but that may
    # not be the same name as the root directory of the content in the sdist
    # (due to case, punctuation, etc.), so after we unpack it look for what was
    # created and ensure the extracted directory matches the override module
    # name and version of the requirement.
    unpacked_root_dir = next(iter(unpack_dir.glob("*")))
    if unpacked_root_dir.name != expected_name:
        desired_name = unpacked_root_dir.parent / expected_name
        try:
            shutil.move(
                str(unpacked_root_dir),
                str(desired_name),
            )
        except Exception as err:
            raise Exception(
                f"Could not rename {unpacked_root_dir.name} to {desired_name}: {err}"
            ) from err
        unpacked_root_dir = desired_name

    return (unpacked_root_dir, True)


def patch_source(
    ctx: context.WorkContext,
    source_root_dir: pathlib.Path,
    req: Requirement,
    version: Version,
) -> None:
    patch_count = 0
    for p in overrides.patches_for_requirement(
        patches_dir=ctx.settings.patches_dir,
        req=req,
        version=version,
    ):
        _apply_patch(p, source_root_dir)
        patch_count += 1

    logger.debug("%s: applied %d patches", req.name, patch_count)
    # If no patch has been applied, call warn for old patch
    if not patch_count:
        _warn_for_old_patch(
            req=req,
            version=version,
            patches_dir=ctx.settings.patches_dir,
        )


def _apply_patch(patch: pathlib.Path, source_root_dir: pathlib.Path):
    logger.info("applying patch file %s to %s", patch, source_root_dir)
    with open(patch, "r") as f:
        external_commands.run(["patch", "-p1"], stdin=f, cwd=source_root_dir)


def _warn_for_old_patch(
    req: Requirement,
    version: Version,
    patches_dir: pathlib.Path,
) -> None:
    # Filter the patch directories using regex
    patch_directories = overrides.get_versioned_patch_directories(
        patches_dir=patches_dir, req=req
    )

    for dirs in patch_directories:
        for p in dirs.iterdir():
            logger.warning(
                f"{req.name}: patch {p} exists but will not be applied for version {version}"
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
    logger.debug("%s: wrote build metadata to %s", req.name, meta_file)
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
    prepare_source_details = overrides.find_and_invoke(
        req.name,
        "prepare_source",
        default_prepare_source,
        ctx=ctx,
        req=req,
        source_filename=source_filename,
        version=version,
    )
    if not isinstance(prepare_source_details, tuple):
        source_root_dir = prepare_source_details
    elif len(prepare_source_details) == 2:
        source_root_dir, _ = prepare_source_details
    else:
        raise ValueError(
            f"do not know how to unpack {prepare_source_details}, expected 1 or 2 members"
        )
    write_build_meta(source_root_dir.parent, req, source_filename, version)
    if source_root_dir is not None:
        logger.info(f"{req.name}: prepared source for {req} at {source_root_dir}")
    return source_root_dir


def default_prepare_source(
    ctx: context.WorkContext,
    req: Requirement,
    source_filename: pathlib.Path,
    version: Version,
) -> tuple[pathlib.Path, bool]:
    """Unpack and modify sdist sources

    Calls :func:`~fromager.sources.prepare_new_source` by default.
    """
    source_root_dir, is_new = unpack_source(
        ctx=ctx,
        req=req,
        version=version,
        source_filename=source_filename,
    )
    if is_new:
        prepare_new_source(
            ctx=ctx,
            req=req,
            source_root_dir=source_root_dir,
            version=version,
        )
    return source_root_dir, is_new


def prepare_new_source(
    ctx: context.WorkContext,
    req: Requirement,
    source_root_dir: pathlib.Path,
    version: Version,
) -> None:
    """Default steps for new sources

    - patch sources
    - apply project overrides from settings
    - vendor Rust dependencies

    :func:`~default_prepare_source` runs this function when the sources are new.
    """
    patch_source(ctx, source_root_dir, req, version)
    pyproject.apply_project_override(
        ctx=ctx,
        req=req,
        sdist_root_dir=source_root_dir,
    )
    vendor_rust.vendor_rust(req, source_root_dir)


def build_sdist(
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    sdist_root_dir: pathlib.Path,
    build_env: build_environment.BuildEnvironment,
) -> pathlib.Path:
    """Build source distribution"""
    pbi = ctx.package_build_info(req)
    build_dir = pbi.build_dir(sdist_root_dir)

    logger.info(f"{req.name}: building source distribution in {build_dir}")
    extra_environ = pbi.get_extra_environ()
    sdist_filename = overrides.find_and_invoke(
        req.name,
        "build_sdist",
        default_build_sdist,
        ctx=ctx,
        extra_environ=extra_environ,
        req=req,
        version=version,
        sdist_root_dir=sdist_root_dir,
        build_dir=build_dir,
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
    build_env: build_environment.BuildEnvironment,
    build_dir: pathlib.Path,
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
    sdist_filename = ctx.sdists_builds / (build_dir.name + ".tar.gz")
    if sdist_filename.exists():
        sdist_filename.unlink()
    # The format argument is specified based on
    # https://peps.python.org/pep-0517/#build-sdist.
    with tarfile.open(sdist_filename, "x:gz", format=tarfile.PAX_FORMAT) as sdist:
        tarballs.tar_reproducible(
            tar=sdist,
            basedir=build_dir,
            prefix=build_dir.parent,
        )
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
        sdist_root_dir,
        pyproject_toml,
        extra_environ,
        network_isolation=ctx.network_isolation,
    )
    sdist_filename = hook_caller.build_sdist(ctx.sdists_builds)
    return ctx.sdists_builds / sdist_filename
