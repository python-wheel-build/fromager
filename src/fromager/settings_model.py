import typing

import yaml
from packaging.utils import NormalizedName, canonicalize_name
from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    HttpUrl,
    ValidationInfo,
    field_validator,
)

from . import overrides

# build variant
Variant = typing.NewType("Variant", str)

# Package validates and transforms name to canonicalized name
Package = typing.Annotated[
    NormalizedName,
    BeforeValidator(lambda pkg: canonicalize_name(pkg, validate=True)),
]

# Set of packages, maps None to empty set
PackageSet = typing.Annotated[
    set[Package],
    BeforeValidator(lambda v: v if v is not None else set()),
]

# URL with templating
UrlTemplate = typing.NewType("UrlTemplate", HttpUrl)


def _map_none_to_default(cls, v: typing.Any, info: ValidationInfo) -> typing.Any:
    if v is None:
        assert info.field_name
        field = cls.model_fields[info.field_name]
        assert field.default_factory
        return field.default_factory()
    return v


class ResolverDist(BaseModel):
    """Packages resolver dist"""

    sdist_server_url: HttpUrl | None = None
    """Source distribution download server"""

    include_sdists: bool = True
    """Include source distribution?"""

    include_wheels: bool = False
    """Include wheels?"""


class DownloadSource(BaseModel):
    """Package download source"""

    url: UrlTemplate | None = None
    """Source download url (string template)"""

    destination_filename: str | None = None
    """Rename file"""


class PackageSettings(BaseModel):
    """Package settings"""

    download_source: DownloadSource = Field(default_factory=DownloadSource)
    resolver_dist: ResolverDist = Field(default_factory=ResolverDist)

    @field_validator("download_source", "resolver_dist", mode="before")
    @classmethod
    def before_none_to_default(cls, v: typing.Any, info: ValidationInfo) -> typing.Any:
        return _map_none_to_default(cls, v, info)


class PackageBuildInfo(BaseModel):
    """Dynamic model with build information"""

    name: Package
    """Canonicalized package name"""

    variant: Variant
    """variant name"""

    pre_built: bool
    """Is the package pre-built?"""

    settings: PackageSettings
    """Package download and built settings"""

    @property
    def override_module_name(self) -> str:
        """Override module name from package name"""
        return overrides.pkgname_to_override_module(self.name)


class Settings(BaseModel):
    """Settings root"""

    packages: dict[Package, PackageSettings] = Field(default_factory=dict)
    """Package build settings overrides"""

    pre_built: dict[Variant, PackageSet] = Field(default_factory=dict)
    """Mark packages as pre-built"""

    @field_validator("packages", "pre_built", mode="before")
    @classmethod
    def before_none_to_default(cls, v: typing.Any, info: ValidationInfo) -> typing.Any:
        """Pre-hook to map None to default factory result"""
        return _map_none_to_default(cls, v, info)

    def get_package(
        self, name: Package | str, *, variant: Variant | str
    ) -> PackageBuildInfo:
        """Get package build information for a variant"""
        name = Package(canonicalize_name(name, validate=True))
        variant = Variant(variant)
        pre_built_set: PackageSet = self.pre_built.get(variant, set())
        ps: PackageSettings | None = self.packages.get(name)
        if ps is None:
            ps = PackageSettings()
        return PackageBuildInfo(
            name=name,
            variant=variant,
            pre_built=name in pre_built_set,
            settings=ps,
        )


def parse_settings(raw_yaml: str) -> Settings:
    """Parse settings from a raw YAML string"""
    parsed: dict[str, typing.Any] = yaml.safe_load(raw_yaml)
    return Settings(**parsed)
