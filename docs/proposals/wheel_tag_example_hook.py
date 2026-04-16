import functools
import os
import platform
import typing

from packaging.requirements import Requirement
from packaging.tags import Tag
from packaging.version import Version

from fromager import context


def example_hook(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    wheel_tags: frozenset[Tag],
) -> typing.Sequence[str]:
    result: list[str] = []
    platlib = any(tag.platform != "any" for tag in wheel_tags)
    if platlib:
        # fc43, el9.6, ...
        result.append(get_distro_tag())
    pbi = ctx.package_build_info(req)

    # example how to use annotations and ctx.variant for custom flags
    if pbi.annotations.get("example.accelerator-specific") == "true":
        # cpu, cuda13.0, ...
        if ctx.variant.startswith("cpu"):
            result.append("cpu")
        elif ctx.variant.startswith("cuda"):
            cv = Version(os.environ["CUDA_VERSION"])
            result.append(f"cuda{cv.major}.{cv.minor}")
        else:
            raise NotImplementedError(ctx.variant)
    return result


@functools.cache
def get_distro_tag() -> str:
    info = platform.freedesktop_os_release()
    ids = [info["ID"]]  # always defined
    if "ID_LIKE" in info:  # ids in precedence order
        ids.extend(info["ID_LIKE"].split())
    version_id = info.get("VERSION_ID", "")
    for ident in ids:
        if ident == "rhel":  # RHEL and CentOS
            return f"el{version_id}"
        elif ident == "fedora":
            return f"fc{version_id}"
    # other distros
    return f"{ids[0]}{version_id}".replace("_", "").replace("-", "")
