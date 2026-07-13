"""Dist-info directory helpers

- https://peps.python.org/pep-0376/
"""

from packaging.utils import parse_wheel_filename


def verbatim_dist_name(wheel_filename: str) -> str:
    """Return the verbatim distribution name from a wheel filename.

    ``parse_wheel_filename`` normalises the name, but the dist-info
    directory inside a wheel uses the original casing (e.g.
    ``MarkupSafe``, not ``markupsafe``).  This helper extracts the
    first ``-``-separated segment after validating the filename.
    """
    parse_wheel_filename(wheel_filename)
    return wheel_filename.split("-", 1)[0]


def dist_info_name(wheel_filename: str) -> str:
    """Return the dist-info directory name for a wheel filename.

    Preserves the verbatim distribution name (e.g. ``MarkupSafe``, not
    ``markupsafe``) because the dist-info directory inside a wheel uses
    the original casing.
    """
    parse_wheel_filename(wheel_filename)
    name, version = wheel_filename.split("-", 2)[:2]
    return f"{name}-{version}.dist-info"
