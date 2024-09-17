#!/usr/bin/env python3

import logging
import pathlib
import re

from packaging.requirements import Requirement
from packaging.utils import BuildTag, canonicalize_name

from . import context, overrides

logger = logging.getLogger(__name__)


def _dist_name_to_filename(dist_name: str) -> str:
    """Transform the dist name into a prefix for a filename.

    Following https://peps.python.org/pep-0427/
    """
    canonical_name = canonicalize_name(dist_name)
    return re.sub(r"[^\w\d.]+", "_", canonical_name, flags=re.UNICODE)


def default_expected_source_archive_name(
    ctx: context.WorkContext,
    req: Requirement,
    dist_version: str,
) -> str | None:
    pbi = ctx.package_build_info(req)
    return pbi.download_source_destination_filename(dist_version)


def find_sdist(
    ctx: context.WorkContext,
    downloads_dir: pathlib.Path,
    req: Requirement,
    dist_version: str,
) -> pathlib.Path | None:
    sdist_file_name = overrides.find_and_invoke(
        req.name,
        "expected_source_archive_name",
        default_expected_source_archive_name,
        req=req,
        dist_version=dist_version,
        ctx=ctx,
    )

    if sdist_file_name:
        sdist_file = downloads_dir / sdist_file_name
        if sdist_file.exists():
            return sdist_file

    else:
        filename_prefix = _dist_name_to_filename(req.name)
        canonical_name = canonicalize_name(req.name)

        candidate_bases = set(
            [
                # First check if the file is there using the canonically
                # transformed name.
                f"{filename_prefix}-{dist_version}",
                # If that didn't work, try the canonical dist name. That's not
                # "correct" but we do see it. (charset-normalizer-3.3.2.tar.gz
                # and setuptools-scm-8.0.4.tar.gz) for example
                f"{canonical_name}-{dist_version}",
                # If *that* didn't work, try the dist name we've been
                # given as a dependency. That's not "correct", either but we do
                # see it. (oslo.messaging-14.7.0.tar.gz) for example
                f"{req.name}-{dist_version}",
                # Sometimes the sdist uses '.' instead of '-' in the
                # package name portion.
                f'{req.name.replace("-", ".")}-{dist_version}',
            ]
        )
        # Case-insensitive globbing was added to Python 3.12, but we
        # have to run with older versions, too, so do our own name
        # comparison.
        for base in candidate_bases:
            for ext in [".tar.gz", ".zip"]:
                logger.debug('%s: looking for sdist as "%s%s"', req.name, base, ext)
                for filename in downloads_dir.glob("*" + ext):
                    if str(filename.name).lower()[: -len(ext)] == base.lower():
                        return filename

    return None


def find_wheel(
    downloads_dir: pathlib.Path,
    req: Requirement,
    dist_version: str,
    build_tag: BuildTag = (),
) -> pathlib.Path | None:
    filename_prefix = _dist_name_to_filename(req.name)
    canonical_name = canonicalize_name(req.name)
    # if build tag is 0 then we can ignore to handle non tagged wheels for backward compatibility
    candidate_bases_build_tag = f"{build_tag[0]}{build_tag[1]}-" if build_tag else ""

    candidate_bases = set(
        [
            # First check if the file is there using the canonically
            # transformed name.
            f"{filename_prefix}-{dist_version}-{candidate_bases_build_tag}",
            # If that didn't work, try the canonical dist name. That's not
            # "correct" but we do see it. (charset-normalizer-3.3.2-
            # and setuptools-scm-8.0.4-) for example
            f"{canonical_name}-{dist_version}-{candidate_bases_build_tag}",
            # If *that* didn't work, try the dist name we've been
            # given as a dependency. That's not "correct", either but we do
            # see it. (oslo.messaging-14.7.0-) for example
            f"{req.name}-{dist_version}-{candidate_bases_build_tag}",
            # Sometimes the sdist uses '.' instead of '-' in the
            # package name portion.
            f'{req.name.replace("-", ".")}-{dist_version}-{candidate_bases_build_tag}',
        ]
    )
    # Case-insensitive globbing was added to Python 3.12, but we
    # have to run with older versions, too, so do our own name
    # comparison.
    for base in candidate_bases:
        logger.debug('%s looking for wheel as "%s"', req.name, base)
        for filename in downloads_dir.glob("*"):
            if str(filename.name).lower().startswith(base.lower()):
                return filename

    return None


def default_expected_source_directory_name(req: Requirement, dist_version: str) -> str:
    raise NotImplementedError


def find_source_dir(
    ctx: context.WorkContext,
    work_dir: pathlib.Path,
    req: Requirement,
    dist_version: str,
) -> pathlib.Path | None:
    sdir_name_func = overrides.find_override_method(
        req.name, "expected_source_directory_name"
    )
    if sdir_name_func:
        # The directory must exist exactly as given, inside the work_dir.
        source_dir_name = overrides.invoke(
            sdir_name_func, req=req, dist_version=dist_version
        )
        source_dir = work_dir / source_dir_name
        if source_dir.exists():
            return source_dir
        raise ValueError(f"looked for {source_dir} and did not find")

    sdist_name = overrides.find_and_invoke(
        req.name,
        "expected_source_archive_name",
        default_expected_source_archive_name,
        req=req,
        dist_version=dist_version,
        ctx=ctx,
    )

    if sdist_name:
        # The directory must exist exactly as given.
        if sdist_name.endswith(".tar.gz"):
            ext_to_strip = ".tar.gz"
        elif sdist_name.endswith(".zip"):
            ext_to_strip = ".zip"
        else:
            raise ValueError(f"Unrecognized extension on {sdist_name}")
        sdist_base_name = sdist_name[: -len(ext_to_strip)]
        source_dir = work_dir / sdist_base_name / sdist_base_name
        if source_dir.exists():
            return source_dir
        raise ValueError(f"looked for {source_dir} and did not find")

    filename_prefix = _dist_name_to_filename(req.name)
    filename_based = f"{filename_prefix}-{dist_version}"
    canonical_name = canonicalize_name(req.name)
    canonical_based = f"{canonical_name}-{dist_version}"
    name_based = f"{req.name}-{dist_version}"
    dotted_name = f'{req.name.replace("-", ".")}-{dist_version}'

    candidate_bases = set(
        [
            # First check if the file is there using the canonically
            # transformed name.
            filename_based,
            # If that didn't work, try the canonical dist name. That's not
            # "correct" but we do see it. (charset-normalizer-3.3.2.tar.gz
            # and setuptools-scm-8.0.4.tar.gz) for example
            canonical_based,
            # If *that* didn't work, try the dist name we've been
            # given as a dependency. That's not "correct", either but we do
            # see it. (oslo.messaging-14.7.0.tar.gz) for example
            name_based,
            # Sometimes the sdist uses '.' instead of '-' in the
            # package name portion.
            dotted_name,
        ]
    )

    # Case-insensitive globbing was added to Python 3.12, but we
    # have to run with older versions, too, so do our own name
    # comparison.
    for base in candidate_bases:
        logger.debug("%s: looking for source directory as %s", req.name, base)
        for dirname in work_dir.glob("*"):
            if str(dirname.name).lower() == base.lower():
                # We expect the unpack directory and the source
                # root directory to be the same. We don't know
                # what case they have, but the pattern matched, so
                # use the base name of the unpack directory to
                # extend the path 1 level.
                return dirname / dirname.name

    return None
