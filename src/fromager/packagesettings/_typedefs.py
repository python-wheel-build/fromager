"""Type aliases, validators, and Annotations class for package settings."""

from __future__ import annotations

import pathlib
import typing
from collections.abc import Mapping

import pydantic
from packageurl import PackageURL
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version
from pydantic import StringConstraints
from pydantic_core import CoreSchema, core_schema

# common settings
MODEL_CONFIG = pydantic.ConfigDict(
    # don't accept unknown keys
    extra="forbid",
    # all fields are immutable
    frozen=True,
    # read inline doc strings
    use_attribute_docstrings=True,
)


# build directory
def _before_builddirectory(p: str) -> pathlib.Path:
    result = pathlib.Path(p)
    if result.is_absolute():
        raise ValueError(f"{result!r} is not a relative path")
    return result


BuildDirectory = typing.Annotated[
    pathlib.Path,
    pydantic.BeforeValidator(_before_builddirectory),
]


# version
class PackageVersion(Version):
    """Pydantic-aware package version"""

    @classmethod
    def validate(cls, v: typing.Any, info: core_schema.ValidationInfo) -> Version:
        if isinstance(v, Version):
            return v
        return Version(v)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: typing.Any, handler: pydantic.GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.with_info_plain_validator_function(
            cls.validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, when_used="json"
            ),
        )


# environment variables map
def _validate_envkey(v: typing.Any) -> str:
    """Validate env key, converts int, float, bool"""
    if isinstance(v, bool):
        return "1" if v else "0"
    elif isinstance(v, int | float):
        return str(v)
    elif not isinstance(v, str):
        raise TypeError(f"unsupported type {type(v)}: {v!r}")
    if "$(" in v:
        raise ValueError(f"'{v}': subshell '$()' is not supported.")
    return v.strip()


EnvKey = typing.Annotated[
    str,
    pydantic.BeforeValidator(_validate_envkey),
]

EnvVars = dict[str, EnvKey]

# Package validates and transforms name to canonicalized name
Package = typing.Annotated[
    NormalizedName,
    pydantic.BeforeValidator(lambda pkg: canonicalize_name(pkg, validate=True)),
]

# patch mapping
PatchMap = dict[Version | None, list[pathlib.Path]]

# URL or filename with templating
Template = typing.NewType("Template", str)

# build variant
Variant = typing.NewType("Variant", str)

# Changelog
GlobalChangelog = Mapping[Variant, list[str]]
VariantChangelog = Mapping[PackageVersion, list[str]]


# purl type (e.g. "pypi", "generic", "github")
PurlType = typing.Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, min_length=1),
]


# full purl string identifying an upstream source package
def _validate_upstream_purl(v: str) -> str:
    """Validate that *v* is a well-formed purl string."""
    try:
        PackageURL.from_string(v)
    except ValueError as err:
        raise ValueError(f"invalid upstream purl {v!r}: {err}") from err
    return v


UpstreamPurl = typing.Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
    pydantic.AfterValidator(_validate_upstream_purl),
]


# Annotations
RawAnnotations = Mapping[str, str]


class Annotations(Mapping):
    """Read-only mapping for package annotations"""

    __slots__ = "_mapping"

    def __init__(
        self,
        package: RawAnnotations | None = None,
        variant: RawAnnotations | None = None,
    ) -> None:
        self._mapping: RawAnnotations = {}
        if package:
            self._mapping.update(package)
        if variant:
            self._mapping.update(variant)

    def __getitem__(self, key: str) -> str:
        return self._mapping[key]

    def __iter__(self) -> typing.Iterator[str]:
        return iter(self._mapping)

    def __len__(self) -> int:
        return len(self._mapping)

    def __repr__(self) -> str:
        return repr(self._mapping)

    def getbool(self, key: str) -> bool:
        """Get bool from string value

        raises :exc:`KeyError` when key is missing and :exc`ValueError` when
        the value is not 1, true, on, yes, 0, false, off, no.
        """
        value = self[key]
        match value.lower():
            case "1" | "true" | "on" | "yes":
                return True
            case "0" | "false" | "off" | "no":
                return False
            case _:
                raise ValueError(value)
