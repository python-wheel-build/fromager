from __future__ import annotations

import logging
import os
import pathlib
import tarfile
import tempfile
import typing
import zipfile
from urllib.parse import unquote, urlparse

from packaging.utils import parse_sdist_filename, parse_wheel_filename
from wheel import wheelfile

from . import gitutils
from .http_retry import RETRYABLE_EXCEPTIONS, retry_on_exception
from .request_session import session

logger = logging.getLogger(__name__)


def extract_filename_from_url(url: str) -> str:
    """Extract filename from URL and decode it."""
    path = urlparse(url).path
    filename = os.path.basename(path)
    return unquote(filename)


def download_url(
    *,
    destination_dir: pathlib.Path,
    url: str,
    destination_filename: str | None = None,
) -> pathlib.Path:
    """Download a URL to destination_dir, returning the local path.

    Returns immediately if the file already exists. Downloads to a
    temporary file in the same directory first and uses :func:`os.rename`
    for an atomic move on success, avoiding partial files. Retries on
    transient network errors.

    .. versionadded:: 0.90.0
    """
    basename = (
        destination_filename if destination_filename else extract_filename_from_url(url)
    )
    outfile = destination_dir / basename
    logger.debug(
        "looking for %s %s",
        outfile,
        "(exists)" if outfile.exists() else "(not there)",
    )
    if outfile.exists():
        logger.debug("already have %s", outfile)
        return outfile

    destination_dir.mkdir(parents=True, exist_ok=True)

    @retry_on_exception(
        exceptions=RETRYABLE_EXCEPTIONS,
        max_attempts=5,
        backoff_factor=1.5,
        max_backoff=120.0,
    )
    def _download_with_retry() -> pathlib.Path:
        """Download to a temporary file, then atomically rename."""
        logger.debug("reading from %s", url)
        # NamedTemporaryFile in the same directory ensures os.rename() is
        # atomic (same filesystem). delete=False so we control cleanup.
        # Temp filename looks like ".tmp.foo-1.2.tar.gz.abc123def".
        tmp = tempfile.NamedTemporaryFile(
            dir=destination_dir,
            prefix=f".tmp.{basename}.",
            delete=False,
        )
        temp_path = pathlib.Path(tmp.name)
        try:
            with session.get(url, stream=True) as r:
                r.raise_for_status()
                logger.debug("writing to %s", temp_path)
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        tmp.write(chunk)
            tmp.close()
            # Atomic rename on the same filesystem
            os.rename(temp_path, outfile)
            logger.info("saved %s", outfile)
            return outfile
        except BaseException:
            tmp.close()
            temp_path.unlink(missing_ok=True)
            raise

    result: pathlib.Path = _download_with_retry()
    return result


def download_sdist(
    *,
    destination_dir: pathlib.Path,
    url: str,
    destination_filename: str | None = None,
) -> pathlib.Path:
    """Download a source distribution and verify it.

    Accepts ``.tar.gz`` and ``.zip`` sdists. Validates the filename
    with :func:`packaging.utils.parse_sdist_filename` before
    downloading and checks that the archive is non-empty afterwards.

    .. note::

       The function does not validate ``PKG-INFO`` metadata or the
       required top-level directory described in the `source distribution
       file format
       <https://packaging.python.org/en/latest/specifications/source-distribution-format/>`_
       specification.

    .. versionadded:: 0.90.0
    """
    basename = (
        destination_filename if destination_filename else extract_filename_from_url(url)
    )
    # Validates name, version, and extension (.tar.gz or .zip);
    # raises InvalidSdistFilename on malformed names.
    parse_sdist_filename(basename)

    filepath = download_url(
        destination_dir=destination_dir,
        url=url,
        destination_filename=basename,
    )

    if basename.endswith(".tar.gz"):
        with tarfile.open(filepath, mode="r:gz") as tar:
            if tar.next() is None:
                raise tarfile.TarError(f"empty tar file: {filepath}")
    elif basename.endswith(".zip"):
        with zipfile.ZipFile(filepath) as zf:
            if not zf.namelist():
                raise zipfile.BadZipFile(f"empty zip file: {filepath}")
    else:
        typing.assert_never(basename)  # type: ignore[arg-type]

    return filepath


def download_wheel(
    *,
    destination_dir: pathlib.Path,
    url: str,
    destination_filename: str | None = None,
) -> pathlib.Path:
    """Download a wheel and verify it.

    Validates that the filename is a valid wheel name (using
    :func:`packaging.utils.parse_wheel_filename`) before downloading,
    then checks that the zip archive is non-empty.

    .. note::

       The function does not validate dist-info ``METADATA`` and other
       files described in the `binary distribution format
       <https://packaging.python.org/en/latest/specifications/binary-distribution-format/>`_
       specification.

    .. versionadded:: 0.90.0
    """
    basename = (
        destination_filename if destination_filename else extract_filename_from_url(url)
    )
    # Validates name, version, build tag, tags, and .whl extension;
    # raises InvalidWheelFilename on malformed names.
    parse_wheel_filename(basename)

    filepath = download_url(
        destination_dir=destination_dir,
        url=url,
        destination_filename=basename,
    )

    # validate wheel file: WheelFile checks for dist-info dir and RECORD.
    # NOTE: Does not validate that METADATA file is valid or consistent with
    #       wheel's distribution name and version.
    # https://packaging.python.org/en/latest/specifications/binary-distribution-format/
    with wheelfile.WheelFile(filepath) as wf:
        di_metadata = f"{wf.dist_info_path}/METADATA"
        if di_metadata not in wf.namelist():
            raise wheelfile.WheelError(f"{di_metadata!r} missing")

    return filepath


def download_git_source(
    *,
    destination_dir: pathlib.Path,
    vcs_url: str,
    require_ref: bool = True,
) -> pathlib.Path:
    """Clone a git repository from a pip VCS URL.

    Parses *vcs_url* with :func:`~fromager.gitutils.parse_vcs_url`
    and clones using :func:`~fromager.gitutils.git_clone_fast`
    with recursive submodules.

    Raises ``FileExistsError`` if the destination directory already
    exists.

    .. versionadded:: 0.90.0
    """
    repo_url, ref = gitutils.parse_vcs_url(vcs_url, require_ref=require_ref)

    # git clone fails when the target directory is not empty.
    try:
        destination_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise FileExistsError(
            f"destination directory {destination_dir} already exists, "
            f"cannot clone {vcs_url}"
        ) from None
    gitutils.git_clone_fast(
        output_dir=destination_dir,
        repo_url=repo_url,
        ref=ref,
    )
    return destination_dir
