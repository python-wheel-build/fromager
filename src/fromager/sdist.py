"""Helpers to normalize arbitrary source directories into valid sdist layout.

Git clones and non-standard tarballs (e.g. GitHub release assets) lack the
``PKG-INFO`` file and standardized directory naming that PEP 517 build
backends expect.  These helpers bridge that gap *before* the build backend
is available -- only the package name and version are required.
"""

from __future__ import annotations

import logging
import pathlib
import shutil
import tarfile

from packaging.version import Version

from . import dependencies, overrides, tarballs

logger = logging.getLogger(__name__)

PKG_INFO_TEMPLATE = """\
Metadata-Version: 2.2
Name: {name}
Version: {version}
Summary: {summary}
"""


def _write_pkg_info(
    directory: pathlib.Path,
    name: str,
    version: Version,
) -> pathlib.Path:
    """Write a stub ``PKG-INFO`` into *directory* if one does not exist.

    Returns the path to the ``PKG-INFO`` file.
    """
    pkg_info_file = directory / "PKG-INFO"
    if not pkg_info_file.is_file():
        logger.info("writing stub PKG-INFO in %s", directory)
        pkg_info_file.write_text(
            PKG_INFO_TEMPLATE.format(
                name=name,
                version=str(version),
                summary=dependencies.STUB_PKG_INFO_SUMMARY,
            )
        )
    return pkg_info_file


def make_sdist_directory(
    source_dir: pathlib.Path,
    name: str,
    version: Version,
    *,
    build_dir: pathlib.Path | None = None,
) -> pathlib.Path:
    """Normalize *source_dir* into a valid sdist directory layout.

    The directory is renamed to ``{normalized_name}-{version}`` (using
    :func:`~fromager.overrides.pkgname_to_override_module`) and a stub
    ``PKG-INFO`` is written if missing.  When *build_dir* differs from
    the source root a second ``PKG-INFO`` is placed there for
    ``setuptools-scm`` compatibility.

    Args:
        source_dir: Path to the source directory (git clone or unpacked
            tarball).
        name: Distribution name (e.g. ``req.name``).
        version: Package version.
        build_dir: Optional non-standard build directory inside
            *source_dir*.  Receives its own ``PKG-INFO`` copy.

    Returns:
        Path to the (possibly renamed) source directory.
    """
    normalized_name = overrides.pkgname_to_override_module(name)
    expected_name = f"{normalized_name}-{version}"

    if source_dir.name != expected_name:
        old_source_dir = source_dir
        desired = source_dir.parent / expected_name
        logger.info(
            "renaming source directory %s -> %s",
            source_dir.name,
            expected_name,
        )
        try:
            shutil.move(str(source_dir), str(desired))
        except Exception as err:
            raise RuntimeError(
                f"Could not rename {source_dir} to {desired}: {err}"
            ) from err
        source_dir = desired

        # Rebase build_dir so it tracks the renamed parent directory.
        if build_dir is not None and build_dir.is_relative_to(old_source_dir):
            build_dir = source_dir / build_dir.relative_to(old_source_dir)

    _write_pkg_info(source_dir, name, version)

    if build_dir is not None and build_dir != source_dir:
        _write_pkg_info(build_dir, name, version)

    return source_dir


def repack_as_sdist(
    source_dir: pathlib.Path,
    name: str,
    version: Version,
    output_dir: pathlib.Path,
    *,
    build_dir: pathlib.Path | None = None,
) -> pathlib.Path:
    """Repack *source_dir* into a standards-compliant sdist tarball.

    Calls :func:`make_sdist_directory` to normalize the layout first,
    then creates a reproducible ``{name}-{version}.tar.gz`` in
    *output_dir*.

    Args:
        source_dir: Path to the source directory.
        name: Distribution name.
        version: Package version.
        output_dir: Directory where the tarball is written.
        build_dir: Optional non-standard build subdirectory.  When set
            the tarball is rooted at *build_dir* (matching
            :func:`~fromager.sources.default_build_sdist` behavior).

    Returns:
        Path to the created ``.tar.gz`` file.
    """
    old_source_dir = source_dir
    source_dir = make_sdist_directory(source_dir, name, version, build_dir=build_dir)

    # Rebase build_dir after a potential rename inside make_sdist_directory.
    if build_dir is not None and source_dir != old_source_dir:
        build_dir = source_dir / build_dir.relative_to(old_source_dir)

    tar_root = build_dir if build_dir is not None else source_dir
    normalized_name = overrides.pkgname_to_override_module(name)
    sdist_filename = output_dir / f"{normalized_name}-{version}.tar.gz"

    if sdist_filename.exists():
        sdist_filename.unlink()

    with tarfile.open(sdist_filename, "x:gz", format=tarfile.PAX_FORMAT) as tar:
        tarballs.tar_reproducible(
            tar=tar,
            basedir=tar_root,
            prefix=tar_root.parent,
        )

    logger.info("created sdist archive %s", sdist_filename)
    return sdist_filename
