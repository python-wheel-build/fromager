"""Vendor Rust crates into an sdist"""

import enum
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


class RustBuildSystem(enum.StrEnum):
    maturin = "maturin"
    setuptools_rust = "setuptools-rust"


def _cargo_vendor(
    req: Requirement,
    manifests: list[pathlib.Path],
    project_dir: pathlib.Path,
) -> typing.Iterable[pathlib.Path]:
    """Run cargo vendor"""
    logger.info(f"updating vendored rust dependencies in {project_dir}")
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


def _detect_rust_build_backend(
    req: Requirement, pyproject_toml: dict[str, typing.Any]
) -> RustBuildSystem | None:
    """Detect Rust requirement and return Rust build system

    Detects setuptools-rust and maturin.
    """
    build_system = dependencies.get_build_backend(pyproject_toml)
    if build_system["build-backend"] == RustBuildSystem.maturin:
        return RustBuildSystem.maturin

    for reqstring in build_system["requires"]:
        req = Requirement(reqstring)
        try:
            # StrEnum.__contains__ does not work with str type
            rbs = RustBuildSystem(req.name)
        except ValueError:
            pass
        else:
            logger.debug(f"build-system requires '{req.name}', vendoring crates")
            return rbs

    logger.debug("no Rust build plugin detected")
    return None


def vendor_generic_rust_package(
    req: Requirement,
    manifests: list[pathlib.Path],
    root_dir: pathlib.Path,
    *,
    shrink_vendored: bool = True,
) -> typing.Iterable[pathlib.Path]:
    """Vendor crates of a generic Rust package"""
    if not manifests:
        # default to Cargo.toml in root dir
        manifests = [root_dir / "Cargo.toml"]
    # fetch and vendor Rust crates
    vendored = _cargo_vendor(req, manifests, root_dir)
    logger.debug(f"vendored crates: {sorted(d.name for d in vendored)}")

    # remove unnecessary pre-compiled files for Windows, macOS, and iOS.
    if shrink_vendored:
        for crate_dir in vendored:
            _cargo_shrink(crate_dir)

    # update or create .cargo/config.toml
    _cargo_config(root_dir)
    return vendored


def vendor_rust(
    req: Requirement, project_dir: pathlib.Path, *, shrink_vendored: bool = True
) -> bool:
    """Vendor Rust crates into a source directory

    Returns ``True`` if the project has a build dependency on
    ``setuptools-rust`` or ``maturin``, and has a ``Cargo.toml``, otherwise
    ``False``.
    """
    pyproject_toml = dependencies.get_pyproject_contents(project_dir)
    if not pyproject_toml:
        logger.debug("has no pyproject.toml")
        return False

    backend = _detect_rust_build_backend(req, pyproject_toml)
    manifests: list[pathlib.Path] = []
    # By default, maturin and setuptools-rust use Cargo.toml from project
    # root directory. Projects can specify a different file in optional
    # "tool.setuptools-rust" or "tool.maturin" entries.
    match backend:
        case RustBuildSystem.maturin:
            try:
                tool_maturin: dict[str, typing.Any] = pyproject_toml["tool"]["maturin"]
            except KeyError as e:
                logger.debug(f"No additional maturin settings: {e}")
            else:
                if "manifest-path" in tool_maturin:
                    manifests.append(project_dir / tool_maturin["manifest-path"])
        case RustBuildSystem.setuptools_rust:
            ext_modules: list[dict[str, typing.Any]]
            try:
                ext_modules = pyproject_toml["tool"]["setuptools-rust"]["ext-modules"]
            except KeyError as e:
                logger.debug(f"No additional setuptools-rust settings: {e}")
            else:
                for ext_module in ext_modules:
                    if "path" in ext_module:
                        manifests.append(project_dir / ext_module["path"])
        case None:
            logger.debug("no Rust build system detected")
            return False
        case _ as unreachable:
            typing.assert_never(unreachable)

    if not manifests:
        # check for Cargo.toml in project root
        root_cargo_toml = project_dir / "Cargo.toml"
        if root_cargo_toml.is_file():
            manifests.append(root_cargo_toml)
        else:
            logger.warning(
                f"Rust build backend {backend} detected, but no Cargo.toml files found."
            )
            return False

    the_manifests = sorted(str(d.relative_to(project_dir)) for d in manifests)
    logger.debug(f"{project_dir} has cargo manifests: {the_manifests}")

    vendor_generic_rust_package(
        req, manifests, project_dir, shrink_vendored=shrink_vendored
    )

    return True
