#!/usr/bin/python3
"""Vendor Rust crates into an sdist
"""
import json
import logging
import pathlib
import typing

import toml

from . import external_commands

logger = logging.getLogger(__name__)

VENDOR_DIR = "vendor"

CARGO_CONFIG = {
    "source": {
        "crates-io": {"replace-with": "vendored-sources"},
        "vendored-sources": {"directory": VENDOR_DIR},
    },
}


def _cargo_vendor(
    manifests: typing.List[pathlib.Path],
    project_dir: pathlib.Path,
) -> typing.Iterable[pathlib.Path]:
    """Run cargo vendor"""
    logger.info("updating vendored rust dependencies in %s", project_dir)
    args = ["cargo", "vendor", f"--manifest-path={manifests[0]}"]
    for manifest in manifests[1:]:
        args.append(f"--sync={manifest}")
    args.append(project_dir / VENDOR_DIR)
    external_commands.run(args)
    return sorted(project_dir.joinpath(VENDOR_DIR).iterdir())


def _cargo_shrink(crate_dir: pathlib.Path):
    """Remove pre-compiled archive and lib files.

    They are only used on Windows, macOS, and iOS. This makes the vendor
    bundle up to 60% smaller. If we ever need these files, then we have to
    figure out how to compile them from sources, too.
    """
    removed_files: typing.List[str] = []
    for pattern in ["**/*.a", "**/*.lib"]:
        for filename in crate_dir.glob(pattern):
            logger.debug("Removing '%s'", filename.relative_to(crate_dir.parent))
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


def _cargo_config(project_dir: pathlib.Path):
    """create .cargo/config.toml"""
    dotcargo = project_dir / ".cargo"
    config_toml = dotcargo / "config.toml"
    try:
        with open(config_toml, "r", encoding="utf-8") as f:
            cfg = toml.load(f)
        logger.debug("Extending existing '.cargo/config.toml'")
    except FileNotFoundError:
        logger.debug("Creating new '.cargo/config.toml'")
        dotcargo.mkdir(exist_ok=True)
        cfg = {}

    cfg.update(CARGO_CONFIG)

    with open(config_toml, "w", encoding="utf-8") as f:
        toml.dump(cfg, f)


def vendor_rust(project_dir: pathlib.Path, *, shrink_vendored: bool = True) -> bool:
    """Vendor Rust crates into a source directory

    Returns ``True`` if the project has a ``Cargo.toml``, otherwise
    ``False``.
    """
    project_name = str(project_dir.name)
    # check for Cargo.toml
    manifests = list(project_dir.glob("**/Cargo.toml"))
    if not manifests:
        logger.debug("%s has no Cargo.toml files", project_name)
        return False

    # setuptools-rust and maturin-based projects have a pyproject.toml
    if not project_dir.joinpath("pyproject.toml").is_file():
        raise ValueError("pyproject.toml is missing")

    logger.debug(
        "%s has cargo maninfests: %s",
        project_name,
        sorted(str(d.relative_to(project_dir)) for d in manifests),
    )
    # fetch and vendor Rust crates
    vendored = _cargo_vendor(manifests, project_dir)
    logger.debug(
        "%s vendored crates: %s",
        project_name,
        sorted(d.name for d in vendored),
    )
    # remove unnecessary pre-compiled files for Windows, macOS, and iOS.
    if shrink_vendored:
        for crate_dir in vendored:
            _cargo_shrink(crate_dir)
    # update or create .cargo/config.toml
    _cargo_config(project_dir)

    return True


def test():
    import argparse
    import tarfile
    import tempfile

    parser = argparse.ArgumentParser()
    parser.add_argument("sdists", type=pathlib.Path, nargs="+")
    parser.add_argument("--outdir", type=pathlib.Path, default="outdir")

    args = parser.parse_args()
    args.outdir.mkdir(exist_ok=True)

    logging.basicConfig(level=logging.INFO)

    for sdist in args.sdists:
        out_sdist = args.outdir / sdist.name
        if out_sdist.is_file():
            out_sdist.unlink()
        logger.info("Vendoring '%s'", sdist)
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            with tarfile.open(sdist) as tar:
                # filter argument was added in 3.10.12, 3.11.4, 3.12.0
                tar.extractall(path=tmpdir, filter="data")

            project_name = sdist.name[: -len(".tar.gz")]
            project_dir = tmpdir / project_name
            vendor_rust(project_dir)

            with tarfile.open(out_sdist, "x:gz") as tar:
                tar.add(project_dir, arcname=project_name)


if __name__ == "__main__":
    test()
