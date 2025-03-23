from __future__ import annotations

import inspect
import json
import logging
import os.path
import pathlib
import shutil
import tarfile
import tempfile
import typing
import zipfile
from email.parser import BytesParser
from urllib.parse import urlparse

import resolvelib
from packaging.requirements import Requirement
from packaging.version import Version

from . import (
    dependencies,
    external_commands,
    gitutils,
    metrics,
    overrides,
    pyproject,
    requirements_file,
    resolver,
    tarballs,
    vendor_rust,
)
from .request_session import session
from .requirements_file import RequirementType

if typing.TYPE_CHECKING:
    from . import build_environment, context

logger = logging.getLogger(__name__)


def get_source_type(ctx: context.WorkContext, req: Requirement) -> str:
    source_type = requirements_file.SourceType.SDIST
    pbi = ctx.package_build_info(req)
    if (
        overrides.find_override_method(req.name, "download_source")
        or overrides.find_override_method(req.name, "resolve_source")
        or overrides.find_override_method(req.name, "get_resolver_provider")
        or pbi.download_source_url(resolve_template=False)
    ):
        source_type = requirements_file.SourceType.OVERRIDE
    return str(source_type)


@metrics.timeit(description="download source")
def download_source(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    download_url: str,
) -> pathlib.Path:
    if req.url:
        logger.info(
            "%s: downloaded source to %s by cloning %s, ignoring any plugins",
            req.name,
            download_url,
            req.url,
        )
        return pathlib.Path(download_url)

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


@metrics.timeit(description="resolve source")
def resolve_source(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    sdist_server_url: str,
    req_type: RequirementType | None = None,
) -> tuple[str, Version]:
    "Return URL to source and its version."

    if req.url and req_type != RequirementType.TOP_LEVEL:
        # Stop processing if we encounter a lower level dependency with a URL.
        raise ValueError(f"{req} includes a URL, but is not a top-level dependency")

    if req.url and req_type == RequirementType.TOP_LEVEL:
        # If we have a URL, we should use that source. For now we only support
        # git clone URLs of some sort. We are given the directory where the
        # cloned repo resides, and return that as the URL for the source code so
        # the next step in the process can find it and operate on it.
        logger.info("%s: resolving source via URL, ignoring any plugins", req.name)
        return resolve_version_from_git_url(ctx=ctx, req=req)

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
            req_type=req_type,
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


def resolve_version_from_git_url(
    ctx: context.WorkContext,
    req: Requirement,
) -> tuple[str, Version]:
    "Return path to the cloned git repository and the package version."

    if not req.url.startswith("git+"):
        raise ValueError(f"unable to handle URL scheme in {req.url} from {req}")

    # We start by not knowing where we would put the source because we don't
    # know the version.
    working_src_dir = ""
    version: Version | None = None

    # Clean up the URL so we can parse it
    reduced_url = req.url[len("git+") :]
    parsed_url = urlparse(reduced_url)

    # Save the URL that we think we will use for cloning. This might change
    # later if the path has a tag or branch in it.
    url_to_clone = reduced_url
    need_to_clone = False

    # If the URL includes an @ with text after it, we use that as the reference
    # to clone, but by default we take the default branch.
    git_ref: str | None = None

    if "@" not in parsed_url.path:
        # If we have no reference, we know we are going to have to clone the
        # repository to figure out the version to use.
        need_to_clone = True
    else:
        # If we have a reference, it might be a valid python version string, or
        # not. It _must_ be a valid git reference. If it can be parsed as a
        # valid python version, we assume the tag points to source that will
        # think that is its version, so we allow reusing an existing cloned repo
        # if there is one.
        new_path, _, git_ref = parsed_url.path.rpartition("@")
        url_to_clone = parsed_url._replace(path=new_path).geturl()
        try:
            version = Version(git_ref)
        except ValueError:
            logger.info(
                "%s: could not parse %r as a version, cloning to get the version",
                req.name,
                git_ref,
            )
            need_to_clone = True
        else:
            logger.info("%s: URL %s includes version %s", req.name, req.url, version)
            working_src_dir = (
                ctx.work_dir / f"{req.name}-{version}" / f"{req.name}-{version}"
            )
            if not working_src_dir.exists():
                need_to_clone = True
            else:
                if ctx.cleanup:
                    logger.debug("%s: cleaning up %s", req.name, working_src_dir)
                    shutil.rmtree(working_src_dir)
                    need_to_clone = True
                else:
                    logger.info("%s: reusing %s", req.name, working_src_dir)

    if need_to_clone:
        with tempfile.TemporaryDirectory() as tmpdir:
            clone_dir = pathlib.Path(tmpdir) / "src"
            gitutils.git_clone(
                ctx=ctx,
                req=req,
                output_dir=clone_dir,
                repo_url=url_to_clone,
                ref=git_ref,
            )
            if not version:
                # If we still do not have a version, get it from the package
                # metadata.
                version = _get_version_from_package_metadata(ctx, req, clone_dir)
                logger.info("%s: found version %s", req.name, version)
                working_src_dir = (
                    ctx.work_dir / f"{req.name}-{version}" / f"{req.name}-{version}"
                )
                if working_src_dir.exists():
                    # We have to check if the destination directory exists
                    # because if we were not given a version we did not clean it
                    # up earlier. We do not use ctx.cleanup to control this
                    # action because we cannot trust that the destination
                    # directory is reusable because we have had to compute the
                    # version and we cannot be sure that the version is dynamic
                    # Two different commits in the repo could have the same
                    # version if that version is set with static data in the
                    # repo instead of via a tag or dynamically computed by
                    # something like setuptools-scm.
                    logger.debug("%s: cleaning up %s", req.name, working_src_dir)
                    shutil.rmtree(working_src_dir)
                    need_to_clone = True
                working_src_dir.parent.mkdir(parents=True, exist_ok=True)
            logger.info("%s: moving cloned repo to %s", req.name, working_src_dir)
            shutil.move(clone_dir, working_src_dir)

    # We must know the version and we must have a source directory.
    assert version
    assert working_src_dir
    assert working_src_dir.exists()
    return (working_src_dir, version)


def _get_version_from_package_metadata(
    ctx: context.WorkContext,
    req: Requirement,
    source_dir: str,
) -> Version:
    logger.info(f"{req.name}: generating metadata to get version")
    pbi = ctx.package_build_info(req)

    hook_caller = dependencies.get_build_backend_hook_caller(
        ctx=ctx,
        req=req,
        sdist_root_dir=source_dir,
        build_dir=pbi.build_dir(source_dir),
        override_environ={},
    )
    metadata_dir_base = hook_caller.prepare_metadata_for_build_wheel(
        metadata_directory=source_dir.parent,
        config_settings={},
    )
    metadata_filename = source_dir.parent / metadata_dir_base / "METADATA"
    with open(metadata_filename, "rb") as f:
        p = BytesParser()
        metadata = p.parse(f, headersonly=True)
    return Version(metadata["Version"])


def default_resolve_source(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_server_url: str,
    req_type: RequirementType | None = None,
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
        req_type=req_type,
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
            if not tar.next():
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
    pbi = ctx.package_build_info(req)
    patch_count = 0

    for p in pbi.get_patches(version):
        _apply_patch(p, source_root_dir)
        patch_count += 1

    logger.debug("%s: applied %d patches", req.name, patch_count)
    # If no patch has been applied, call warn for old patch
    patchmap = pbi.get_all_patches()
    if not patch_count and patchmap:
        for patchversion in sorted(patchmap):
            logger.warning(
                f"{req.name}: patch {patchversion} exists but will not be applied for version {version}"
            )


def _apply_patch(patch: pathlib.Path, source_root_dir: pathlib.Path):
    logger.info("applying patch file %s to %s", patch, source_root_dir)
    with open(patch, "r") as f:
        external_commands.run(["patch", "-p1"], stdin=f, cwd=source_root_dir)


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


@metrics.timeit(description="prepare source")
def prepare_source(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    source_filename: pathlib.Path,
    version: Version,
) -> pathlib.Path:
    if req.url:
        logger.info(
            "%s: preparing source cloned from %s, ignoring any plugins",
            req.name,
            req.url,
        )
        source_root_dir = pathlib.Path(source_filename)
        prepare_new_source(
            ctx=ctx,
            req=req,
            source_root_dir=source_root_dir,
            version=version,
        )
    else:
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


@metrics.timeit(description="build sdist")
def build_sdist(
    *,
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
    extra_environ = pbi.get_extra_environ(build_env=build_env)
    if req.url:
        # The default approach to making an sdist is to make a tarball from the
        # source directory, since most of the time we got the source directory
        # by unpacking an existing sdist. When we know we cloned a git repo to
        # get the source tree, we can be very sure that creating a tarball will
        # NOT produce a valid sdist, so we can use the PEP-517 approach
        # instead.
        logger.info("%s: using PEP-517 sdist build, ignoring any plugins", req.name)
        sdist_filename = pep517_build_sdist(
            ctx=ctx,
            extra_environ=extra_environ,
            req=req,
            sdist_root_dir=sdist_root_dir,
            version=version,
        )
    else:
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
    sdist_filename = ctx.sdists_builds / f"{req.name}-{version}.tar.gz"
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
    pbi = ctx.package_build_info(req)
    hook_caller = dependencies.get_build_backend_hook_caller(
        ctx=ctx,
        req=req,
        sdist_root_dir=sdist_root_dir,
        build_dir=pbi.build_dir(sdist_root_dir),
        override_environ=extra_environ,
    )
    sdist_filename = hook_caller.build_sdist(ctx.sdists_builds)
    return ctx.sdists_builds / sdist_filename
