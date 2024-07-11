# SPDX-License-Identifier: Apache-2.0
"""Change wheel version"""

import pathlib
from email.generator import BytesGenerator
from email.message import Message
from email.parser import BytesParser
from email.policy import EmailPolicy, compat32

from auditwheel.wheeltools import InWheelCtx
from packaging.tags import Tag
from packaging.utils import BuildTag, NormalizedName, parse_wheel_filename
from packaging.version import LocalType, Version

__all__ = ("change_wheel_version",)


def join_wheel_filename(
    name: NormalizedName,
    version: Version,
    buildtag: BuildTag,
    tags: frozenset[Tag],
) -> str:
    """Make a wheel file name from its components"""
    parts = [str(name), str(version)]
    if buildtag:
        parts.append(f"{buildtag[0]}{buildtag[1]}")
    parts.extend(str(tag) for tag in tags)
    return "-".join(parts) + ".whl"


def read_pkg_info(pkg_info_path: pathlib.Path) -> Message:
    """Read a package info file"""
    with pkg_info_path.open("rb") as f:
        return BytesParser(policy=compat32).parse(f)


def write_pkg_info(pkg_info_path: pathlib.Path, msg: Message) -> None:
    """Write a package info file"""
    policy = EmailPolicy(
        utf8=True,
        mangle_from_=False,
        max_line_length=0,
    )
    with pkg_info_path.open("wb") as f:
        BytesGenerator(f, maxheaderlen=0, policy=policy).flatten(msg)


def update_version(
    version: Version,
    *,
    post: int | None = None,
    local: LocalType | None = None,
) -> Version:
    """Update post and local bits of packaging Version

    Version class has no API to update elements. We re-implement its
    __str__() method with small modifications to create a version string,
    then create a new Version object from the string.
    """
    # see Version.__str__
    parts = []

    # Epoch
    if version.epoch != 0:
        parts.append(f"{version.epoch}!")

    # Release segment
    parts.append(".".join(str(x) for x in version.release))

    # Pre-release
    if version.pre is not None:
        parts.append("".join(str(x) for x in version.pre))

    # Post-release
    if post is not None:
        parts.append(f".post{post}")
    elif version.post is not None:
        parts.append(f".post{version.post}")

    # Development release
    if version.dev is not None:
        parts.append(f".dev{version.dev}")

    # Local version segment
    if local:
        parts.append(f"+{'.'.join(str(x) for x in local)}")
    elif version.local is not None:
        parts.append(f"+{version.local}")

    return Version("".join(parts))


def change_wheel_version(
    wheel_in: pathlib.Path,
    *,
    post: int | None = None,
    local: LocalType | None = None,
    outdir: pathlib.Path | None = None,
) -> pathlib.Path:
    """Change the local version and post number of a wheel file

    - post: post version number, int >= 0
    - local: tuple of local version items

    "shrubbery-42.0-py3-none-any.whl" -> "shrubbery-42.0.post23+egg.spam-py3-none-any.whl"
    """
    # validate parameters
    if post < 0:
        raise ValueError("Invalid post '{post}', must be >= 0.")
    # https://packaging.python.org/en/latest/specifications/version-specifiers/#local-version-identifiers
    for loc in local:
        if not loc.isalnum():
            raise ValueError("Invalid local item '{loc}', must alphanumeric.")

    wheel_in = wheel_in.absolute()
    name, oldversion, buildtag, tags = parse_wheel_filename(wheel_in.name)
    newversion = update_version(oldversion, post=post, local=local)

    if outdir is None:
        outdir = wheel_in.parent
    wheel_out = outdir.joinpath(join_wheel_filename(name, newversion, buildtag, tags))

    with InWheelCtx(wheel_in, wheel_out) as ctx:
        ctxpath = pathlib.Path(ctx.path)
        # rename dist-info directory
        old_dist_info = ctxpath.joinpath(f"{name}-{oldversion}.dist-info")
        new_dist_info = ctxpath.joinpath(f"{name}-{newversion}.dist-info")
        old_dist_info.rename(new_dist_info)
        # update version header in metadata
        metadata_fname = new_dist_info.joinpath("METADATA")
        msg = read_pkg_info(metadata_fname)
        msg.replace_header("Version", str(newversion))
        write_pkg_info(metadata_fname, msg)

    return wheel_out
