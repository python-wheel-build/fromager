"""Vendor Rust crates into an sdist"""

import json
import logging
import os
import pathlib
import typing

import tomlkit
from packaging.requirements import Requirement

from . import dependencies, external_commands

logger = logging.getLogger(__name__)

VENDOR_DIR = "vendor"

CARGO_CONFIG = {
    "source": {
        "crates-io": {"replace-with": "vendored-sources"},
        "vendored-sources": {"directory": VENDOR_DIR},
    },
}

# vendor when project depends on a Rust build system
RUST_BUILD_REQUIRES = frozenset({"setuptools-rust", "maturin"})


def _cargo_vendor(
    req: Requirement,
    manifests: list[pathlib.Path],
    project_dir: pathlib.Path,
) -> typing.Iterable[pathlib.Path]:
    """Run cargo vendor"""
    logger.info(f"{req.name}: updating vendored rust dependencies in {project_dir}")
    args = ["cargo", "vendor", f"--manifest-path={manifests[0]}"]
    for manifest in manifests[1:]:
        args.append(f"--sync={manifest}")
    args.append(os.fspath(project_dir / VENDOR_DIR))
    external_commands.run(args, network_isolation=False)
    return sorted(project_dir.joinpath(VENDOR_DIR).iterdir())


def _cargo_shrink(crate_dir: pathlib.Path) -> None:
    """Remove pre-compiled archive and lib files.

    They are only used on Windows, macOS, and iOS. This makes the vendor
    bundle up to 60% smaller. If we ever need these files, then we have to
    figure out how to compile them from sources, too.
    """
    removed_files: list[str] = []
    for pattern in ["**/*.a", "**/*.lib"]:
        for filename in crate_dir.glob(pattern):
            logger.debug("removing '%s'", filename.relative_to(crate_dir.parent))
            filename.unlink()
            filename.touch()  # create empty file
            removed_files.append(str(filename.relative_to(crate_dir)))

    # update checksums
    checksum_file = crate_dir.joinpath(".cargo-checksum.json")
    if removed_files and checksum_file.is_file():
        with checksum_file.open("r", encoding="utf-8") as f:
            checksums = json.load(f)
        for rf in removed_files:
            checksums["files"].pop(rf, None)
        with checksum_file.open("w", encoding="utf-8") as f:
            json.dump(checksums, f)


def _cargo_config(project_dir: pathlib.Path) -> None:
    """create .cargo/config.toml"""
    dotcargo = project_dir / ".cargo"
    config_toml = dotcargo / "config.toml"
    try:
        with open(config_toml, "r", encoding="utf-8") as f:
            cfg = tomlkit.load(f)
        logger.debug("extending existing '.cargo/config.toml'")
    except FileNotFoundError:
        logger.debug("creating new '.cargo/config.toml'")
        dotcargo.mkdir(exist_ok=True)
        cfg = tomlkit.parse("")

    cfg.update(CARGO_CONFIG)

    with open(config_toml, "w", encoding="utf-8") as f:
        tomlkit.dump(cfg, f)


def _should_vendor_rust(req: Requirement, project_dir: pathlib.Path) -> bool:
    """Detect if project has build requirement on Rust

    Detects setuptools-rust and maturin.
    """
    pyproject_toml = dependencies.get_pyproject_contents(project_dir)
    if not pyproject_toml:
        logger.debug(f"{req.name}: has no pyproject.toml")
        return False

    build_backend = dependencies.get_build_backend(pyproject_toml)

    for reqstring in build_backend["requires"]:
        req = Requirement(reqstring)
        if req.name in RUST_BUILD_REQUIRES:
            logger.debug(
                f"{req.name}: build-system requires {req.name}, vendoring crates"
            )
            return True

    logger.debug(f"{req.name}: no Rust build plugin detected")
    return False


def vendor_rust(
    req: Requirement, project_dir: pathlib.Path, *, shrink_vendored: bool = True
) -> bool:
    """Vendor Rust crates into a source directory

    Returns ``True`` if the project has a build dependency on
    ``setuptools-rust`` or ``maturin``, and has a ``Cargo.toml``, otherwise
    ``False``.
    """
    if not _should_vendor_rust(req, project_dir):
        return False

    # check for Cargo.toml
    manifests = list(project_dir.glob("**/Cargo.toml"))
    if not manifests:
        logger.debug(f"{req.name}: has no Cargo.toml files")
        return False

    the_manifests = sorted(str(d.relative_to(project_dir)) for d in manifests)
    logger.debug(f"{req.name}: {project_dir} has cargo manifests: {the_manifests}")

    # fetch and vendor Rust crates
    vendored = _cargo_vendor(req, manifests, project_dir)
    logger.debug(f"{req.name}: vendored crates: {sorted(d.name for d in vendored)}")

    # remove unnecessary pre-compiled files for Windows, macOS, and iOS.
    if shrink_vendored:
        for crate_dir in vendored:
            _cargo_shrink(crate_dir)
    # update or create .cargo/config.toml
    _cargo_config(project_dir)

    return True
