"""Pydantic model classes."""

from __future__ import annotations

import logging
import os
import pathlib
import typing
from collections.abc import Mapping

import pydantic
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from pydantic import AnyUrl, Field
from pydantic_core import core_schema

from ._typedefs import (
    MODEL_CONFIG,
    BuildDirectory,
    EnvVars,
    Package,
    PurlType,
    RawAnnotations,
    Template,
    UpstreamPurl,
    Variant,
    VariantChangelog,
)

logger = logging.getLogger(__name__)


class SbomSettings(pydantic.BaseModel):
    """Global SBOM generation settings

    ::

      sbom:
        supplier: "Organization: ExampleCo"
        namespace: "https://www.example.com"
        purl_type: pypi
        repository_url: "https://example.com/simple"
        creators:
          - "Organization: ExampleCo"
    """

    model_config = MODEL_CONFIG

    supplier: str = "NOASSERTION"
    """SPDX supplier field for the wheel package (e.g. ``Organization: ExampleCo``)"""

    namespace: AnyUrl = AnyUrl("https://spdx.org/spdxdocs")
    """Base URL for the SPDX documentNamespace"""

    creators: list[str] = Field(default_factory=list)
    """Additional SPDX creator entries (e.g. ``Organization: ExampleCo``)

    The fromager tool creator entry is always added automatically.
    """

    purl_type: PurlType = "pypi"
    """Default purl type for all packages (e.g. ``pypi``, ``generic``)"""

    repository_url: AnyUrl | None = None
    """Default purl ``repository_url`` qualifier for all packages

    When set, this URL is added to every purl as a qualifier
    (e.g. ``pkg:pypi/flask@2.0?repository_url=https://example.com/simple``).
    Can be overridden per-package in the package settings file.
    """


class PurlConfig(pydantic.BaseModel):
    """Per-package purl configuration for SBOM generation.

    Allows overriding individual purl components or specifying an
    upstream purl for packages sourced from GitHub/GitLab.

    .. versionadded:: 0.81.0

    ::

      purl:
        type: generic
        name: custom-name
        repository_url: "https://example.com/simple"
        upstream: "pkg:github/org/repo@v1.0.0"
    """

    model_config = MODEL_CONFIG

    type: PurlType | None = None
    """Override the purl type (e.g. ``generic`` instead of ``pypi``)"""

    namespace: str | None = None
    """Override the purl namespace component"""

    name: str | None = None
    """Override the purl name component (defaults to the package name)"""

    version: str | None = None
    """Override the purl version component (defaults to the resolved version)"""

    repository_url: AnyUrl | None = None
    """Per-package override for the purl ``repository_url`` qualifier.

    Overrides the global ``sbom.repository_url`` setting for this package.
    """

    upstream: UpstreamPurl | None = None
    """Full purl string identifying the upstream source package.

    When set, this is used as the upstream identity in the SBOM's
    GENERATED_FROM relationship. Used for packages sourced from
    GitHub/GitLab rather than PyPI.

    When absent, the upstream purl is auto-derived from the downstream
    purl without the ``repository_url`` qualifier.
    """


class ResolverDist(pydantic.BaseModel):
    """Packages resolver dist

    ::

      sdist_server_url: https://pypi.org/simple/
      include_sdists: True
      include_wheels: False
      ignore_platform: False
    """

    model_config = MODEL_CONFIG

    sdist_server_url: str | None = None
    """Source distribution download server (default: PyPI)"""

    include_sdists: bool = True
    """Use sdists to resolve? (default: yes)"""

    include_wheels: bool = False
    """Use wheels to resolve? (default: no)"""

    ignore_platform: bool = False
    """Ignore the platform when resolving with wheels? (default: no)

    This option ignores the platform field (OS, CPU arch) when resolving with
    *include_wheels* enabled.

    .. versionadded:: 0.52
    """

    use_pypi_org_metadata: bool | None = None
    """Can use metadata from pypi.org JSON / Simple API?

    None (default) is for auto-setting. Packages with customizations (config,
    patches, plugins) don't use pypi.org metadata by default.

    .. versionadded:: 0.70
    """

    min_release_age: int | None = pydantic.Field(default=None, ge=0)
    """Per-package minimum release age override in days.

    None (default): inherit the global ``--min-release-age`` setting.
    0: disable the release-age cooldown for this package.
    Positive integer: override the cooldown with this many days.

    .. versionadded:: 0.82
    """

    @pydantic.model_validator(mode="after")
    def validate_ignore_platform(self) -> typing.Self:
        if self.ignore_platform and not self.include_wheels:
            raise ValueError(
                "'ignore_platforms' has no effect without 'include_wheels'"
            )
        return self


class DownloadSource(pydantic.BaseModel):
    """Package download source

    Download package sources from an alternative source, e.g. GitHub release.

    ::

        url: https://example.com/package.tar.gz
        destination_filename: ${dist_name}-${version}.tar.gz
    """

    model_config = MODEL_CONFIG

    url: Template | None = None
    """Source download url (string template)"""

    destination_filename: Template | None = None
    """Rename file (filename without path)"""

    @pydantic.field_validator("destination_filename")
    @classmethod
    def validate_destination_filename(cls, v: str) -> str:
        if os.pathsep in v:
            raise ValueError(f"must not contain {os.pathsep}")
        return v


class BuildOptions(pydantic.BaseModel):
    """Build system options

    ::

        build_ext_parallel: False  # DEPRECATED: ignored, will be removed
        cpu_cores_per_job: 1
        memory_per_job_gb: 1.0
    """

    model_config = MODEL_CONFIG

    build_ext_parallel: bool = False
    """Configure `build_ext[parallel]` in `DIST_EXTRA_CONFIG`

    .. deprecated:: 0.72.0
       This option is deprecated and will be removed in a future release.
       The parallel build feature for extensions is unsafe due to race conditions.
       This option is now ignored and will emit a warning if set to True.
    """

    cpu_cores_per_job: int = Field(default=1, ge=1)
    """Scale parallel jobs by available CPU cores

    Examples:

    1: as many parallel jobs as CPU logical cores

    2: allocate 2 cores per job
    """

    memory_per_job_gb: float = Field(default=1.0, ge=0.1)
    """Scale parallel jobs by available virtual memory (without swap)

    Examples:

    0.5: assume each parallel job requires 512 MB virtual memory
    """

    exclusive_build: bool = False
    """If true, this package must be built on its own (not in parallel with other packages). Default: False."""


class ProjectOverride(pydantic.BaseModel):
    """Override pyproject.toml settings

    ::

      update_build_requires:
        - setuptools
      remove_build_requires:
        - ninja
      requires_external:
        - openssl-libs
    """

    model_config = MODEL_CONFIG

    update_build_requires: list[str] = Field(default_factory=list)
    """Add / update requirements to pyproject.toml `[build-system] requires`
    """

    remove_build_requires: list[Package] = Field(default_factory=list)
    """Remove requirement from pyproject.toml `[build-system] requires`
    """

    requires_external: list[str] = Field(default_factory=list)
    """Add / update Requires-External core metadata field

    Each entry contains a string describing some dependency in the system
    that the distribution is to be used. See
    https://packaging.python.org/en/latest/specifications/core-metadata/#requires-external-multiple-use

    .. note::
       Fromager does not modify ``METADATA`` file, yet. Read the information
       from an ``importlib.metadata`` distribution with
       ``tomlkit.loads(dist(pkgname).read_text("fromager-build-settings"))``.
    """

    @pydantic.field_validator("update_build_requires")
    @classmethod
    def validate_update_build_requires(cls, v: list[str]) -> list[str]:
        for reqstr in v:
            Requirement(reqstr)
        return v


class VariantInfo(pydantic.BaseModel):
    """Variant information for a package

    ::

      env:
        VAR1: "value 1"
        VAR2: "2.0
      wheel_server_url: https://pypi.org/simple/
      pre_build: False
    """

    model_config = MODEL_CONFIG

    annotations: RawAnnotations | None = None
    """Arbitrary metadata for variants

    Variant annotation keys have a higher precedence than package
    annotation keys.
    """

    env: EnvVars = Field(default_factory=dict)
    """Additional env vars (overrides package env vars)"""

    wheel_server_url: str | None = None
    """Alternative package index for pre-built wheel"""

    pre_built: bool = False
    """Use pre-built wheel from index server?"""


class GitOptions(pydantic.BaseModel):
    """Git repository cloning options

    ::

        submodules: False
        submodule_paths: []
    """

    model_config = MODEL_CONFIG

    submodules: bool = False
    """Clone git submodules recursively?

    When True, all submodules will be cloned recursively.
    When False (default), no submodules will be cloned.
    """

    submodule_paths: list[str] = Field(default_factory=list)
    """Clone specific submodule paths only

    If provided, only the specified submodule paths will be cloned.
    This option takes precedence over the 'submodules' boolean setting.

    Examples:
    - ["third-party/openssl"]
    - ["vendor/lib1", "vendor/lib2"]
    """


_DictStrAny = dict[str, typing.Any]


class PackageSettings(pydantic.BaseModel):
    """Package settings

    ::

        build_dir: python
        changelog:
            "1.0.1":
                - fixed bug
        env:
            EGG: spam
        download_source:
            url: https://egg.test
            destination_filename: new_filename
        resolver_dist:
            sdist_server_url: https://sdist.test/egg
            include_sdists: true
            include_wheels: false
        build_options:
            build_ext_parallel: False
            cpu_cores_per_job: 1
            memory_per_job_gb: 1.0
            exclusive_build: False
        variants:
            cpu:
                env:
                    EGG: spamalot
                wheel_server_url: https://wheel.test/simple
            rocm:
                pre_built: True
    """

    model_config = MODEL_CONFIG

    name: Package
    """Canonicalized package name"""

    has_config: bool
    """package has override setting"""

    annotations: RawAnnotations | None = None
    """Arbitrary metadata for a package"""

    build_dir: BuildDirectory | None = None
    """sub-directory with setup.py or pyproject.toml"""

    changelog: VariantChangelog = Field(default_factory=dict)
    """Changelog entries"""

    config_settings: dict[str, str | list[str]] = Field(default_factory=dict)
    """PEP 517 arbitrary configuration for wheel builds

    https://peps.python.org/pep-0517/#config-settings

    ::

       config_settings:
         setup-args:
           - "-Dsystem-freetype=true"
           - "-Dsystem-qhull=true"
    """

    env: EnvVars = Field(default_factory=dict)
    """Common env var for all variants"""

    download_source: DownloadSource = Field(default_factory=DownloadSource)
    """Alternative source download settings"""

    purl: PurlConfig | None = None
    """Purl configuration for SBOM generation.

    A ``PurlConfig`` object with individual field overrides and upstream
    source identification.

    .. versionchanged:: 0.81.0
       The *purl* option now requires a valid PURL config object instead of a string.
    """

    resolver_dist: ResolverDist = Field(default_factory=ResolverDist)
    """Resolve distribution version"""

    build_options: BuildOptions = Field(default_factory=BuildOptions)
    """Build system options"""

    git_options: GitOptions = Field(default_factory=GitOptions)
    """Git repository cloning options"""

    project_override: ProjectOverride = Field(default_factory=ProjectOverride)
    """Patch project settings"""

    variants: Mapping[Variant, VariantInfo] = Field(default_factory=dict)
    """Variant configuration"""

    @pydantic.field_validator(
        "download_source", "resolver_dist", "git_options", "variants", mode="before"
    )
    @classmethod
    def before_none_dict(
        cls, v: _DictStrAny | None, info: core_schema.ValidationInfo
    ) -> _DictStrAny:
        if v is None:
            v = {}
        return v

    @classmethod
    def from_mapping(
        cls,
        package: str | Package,
        parsed: dict[str, typing.Any],
        *,
        source: pathlib.Path | str | None,
        has_config: bool,
    ) -> PackageSettings:
        """Load from a dict"""
        package = Package(canonicalize_name(package, validate=True))
        try:
            return cls(name=package, has_config=has_config, **parsed)
        except Exception as err:
            raise RuntimeError(
                f"{package}: failed to load settings (source: {source!r}): {err}"
            ) from err

    @classmethod
    def from_string(
        cls,
        package: str | Package,
        raw_yaml: str,
        *,
        source: pathlib.Path | str | None = None,
    ) -> PackageSettings:
        """Load from raw yaml string"""
        parsed: typing.Any = yaml.safe_load(raw_yaml)
        if parsed is None:
            # empty file
            parsed = {}
        elif not isinstance(parsed, Mapping):
            raise TypeError(
                f"{package}: invalid yaml, not a dict (source: {source!r}): {parsed}"
            )
        return cls.from_mapping(package, parsed, source=source, has_config=True)

    @classmethod
    def from_file(cls, filename: pathlib.Path) -> PackageSettings:
        """Load from file

        Raises :exc:`FileNotFound` when the file is not found.
        The package name is taken from the stem of the file name.
        """
        filename = filename.absolute()
        logger.debug("loading package config from %s", filename)
        raw_yaml = filename.read_text(encoding="utf-8")
        return cls.from_string(filename.stem, raw_yaml, source=filename)

    @classmethod
    def from_default(cls, package: str | Package) -> PackageSettings:
        """Create a default package setting"""
        return cls.from_mapping(package, {}, source="default", has_config=False)

    @property
    def override_module_name(self) -> str:
        """Override module name from package name"""
        return self.name.replace("-", "_")

    def serialize(
        self,
        mode: str = "python",
        exclude_defaults: bool = True,
        exclude_unset: bool = True,
        exclude: set[str] | frozenset[str] = frozenset({"name", "has_config"}),
        **kwargs: typing.Any,
    ) -> dict[str, typing.Any]:
        """Serialize package configuration"""
        return self.model_dump(
            mode=mode,
            # exclude defaults
            exclude_defaults=exclude_defaults,
            exclude_unset=exclude_unset,
            # name and has_config are not serialized
            exclude=set(exclude),
            **kwargs,
        )
