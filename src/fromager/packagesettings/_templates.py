"""Template substitution functions."""

from __future__ import annotations

import logging
import re
import string

from packaging.version import Version

from ._typedefs import Package, Template

logger = logging.getLogger(__name__)


def _resolve_template(
    template: Template,
    pkg: Package,
    version: Version | None = None,
) -> str:
    template_env: dict[str, str] = {"canonicalized_name": str(pkg)}
    if version:
        template_env["version"] = str(version)

    try:
        return string.Template(template).substitute(template_env)
    except KeyError:
        logger.warning(
            f"{pkg}: couldn't resolve url or name for {template} using the template: {template_env}"
        )
        raise


_DEFAULT_PATTERN_RE = re.compile(
    r"(?<!\$)"  # not preceeded by a second '$'
    r"\$\{(?P<name>[a-z0-9_]+)"  # '${name'
    r"(:-(?P<default>[^\}:]*))?"  # optional ':-default', capture value
    r"\}",  # closing '}'
    flags=re.ASCII | re.IGNORECASE,
)


def substitute_template(value: str, template_env: dict[str, str]) -> str:
    """Substitute ${var} and ${var:-default} in value string"""
    localdefault = template_env.copy()
    for mo in _DEFAULT_PATTERN_RE.finditer(value):
        modict = mo.groupdict()
        name = modict["name"]
        default = modict["default"]
        # Only set the default if one is explicitly provided.
        # This ensures that undefined variables without defaults
        # will raise KeyError later
        if default is not None:
            localdefault.setdefault(name, default)
            # Replace ${var:-default} with ${var}
            value = value.replace(mo.group(0), f"${{{name}}}")
    try:
        return string.Template(value).substitute(localdefault)
    except KeyError as e:
        raise ValueError(
            f"Undefined environment variable {e!r} referenced in expression {value!r}"
        ) from e
