"""Generate wheel tags for any CPython version and ABI.

``packaging.tags.sys_tags()`` reads the running interpreter.  These
helpers also describe a target version that is not running, including
free-threaded builds.  GIL builds use the ``abi3`` stable ABI.
Free-threaded builds use ``abi3t`` (PEP 803).  One multi-ABI wheel,
for example ``cp315-abi3.abi3t``, serves both.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator

from packaging.tags import Tag, compatible_tags, cpython_tags, platform_tags


def cpython_target_tags(
    python_version: tuple[int, int] | None = None,
    free_threaded: bool | None = None,
    platforms: list[str] | None = None,
) -> Iterator[Tag]:
    """Yield compatible wheel tags for a CPython target.

    The order is the same as in ``packaging.tags.sys_tags()``.  The
    interpreter-specific tags come first.  Then the ``py3-none-*``
    fallbacks follow.

    Args:
        python_version: Target version, for example ``(3, 15)``.
            Defaults to ``sys.version_info[:2]``.
        free_threaded: Target a free-threaded build (``cp315t`` instead
            of ``cp315``).  Defaults to the running interpreter.
        platforms: Platform tag strings.  Defaults to
            ``packaging.tags.platform_tags()``.
    """
    if python_version is None:
        python_version = sys.version_info[:2]

    if free_threaded is None:
        free_threaded = "t" in getattr(sys, "abiflags", "")

    verdot = f"{python_version[0]}{python_version[1]}"

    if free_threaded:
        abis = [f"cp{verdot}t"]
    else:
        abis = [f"cp{verdot}"]

    if platforms is None:
        platforms = list(platform_tags())

    interp = f"cp{verdot}"

    # Interpreter-specific tags (with ABI, stable ABI, none)
    yield from cpython_tags(
        python_version=python_version,
        abis=abis,
        platforms=platforms,
    )
    # Generic compatible tags (py3-none-*, cpXY-none-any, py3-none-any)
    yield from compatible_tags(
        python_version=python_version,
        interpreter=interp,
        platforms=platforms,
    )


_CPYTHON_TAG_RE = re.compile(r"cp(\d)(\d+)(t?)")


def parse_cpython_tag(tag: str) -> tuple[tuple[int, int], bool]:
    """Split a CPython tag such as ``"cp314"`` or ``"cp314t"``.

    Returns the ``(python_version, free_threaded)`` arguments that
    `cpython_target_tags` accepts.

    Args:
        tag: CPython tag from a wheel's interpreter field.

    Returns:
        ``(python_version, free_threaded)``, for example
        ``((3, 14), True)``.

    Raises:
        ValueError: If *tag* is not of the form ``cpXYZ[t]``.
    """
    m = _CPYTHON_TAG_RE.fullmatch(tag)
    if not m:
        raise ValueError(
            f"invalid CPython tag {tag!r}, expected format like 'cp314' or 'cp314t'"
        )
    major = int(m.group(1))
    minor = int(m.group(2))
    free_threaded = m.group(3) == "t"
    return (major, minor), free_threaded


def current_cpython_tag() -> str:
    """Return the tag of the running interpreter, for example ``"cp314"``.

    A free-threaded build gets a ``t`` suffix, for example ``"cp313t"``.
    """
    verdot = f"{sys.version_info[0]}{sys.version_info[1]}"
    suffix = "t" if "t" in getattr(sys, "abiflags", "") else ""
    return f"cp{verdot}{suffix}"
