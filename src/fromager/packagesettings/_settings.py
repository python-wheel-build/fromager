"""SettingsFile and Settings classes."""

from __future__ import annotations

import logging
import pathlib
import typing
from collections.abc import Mapping

import pydantic
import yaml
from packaging.utils import canonicalize_name
from pydantic import Field

from .. import overrides
from ._models import PackageSettings
from ._pbi import PackageBuildInfo
from ._typedefs import MODEL_CONFIG, GlobalChangelog, Package, Variant

logger = logging.getLogger(__name__)


class SettingsFile(pydantic.BaseModel):
    """Models global settings file `settings.yaml`

    ::

      changelog:
        cuda:
          - "2024-09-13: updated CUDA version"
        rocm:
          - "2024-09-01: updated ROCm version"
    """

    model_config = MODEL_CONFIG

    changelog: GlobalChangelog = Field(default_factory=dict)
    """Changelog entries"""

    @classmethod
    def from_string(
        cls,
        raw_yaml: str,
        *,
        source: pathlib.Path | str | None = None,
    ) -> SettingsFile:
        """Load from raw yaml string"""
        parsed: typing.Any = yaml.safe_load(raw_yaml)
        if parsed is None:
            # empty file
            parsed = {}
        elif not isinstance(parsed, Mapping):
            raise TypeError(f"invalid yaml, not a dict (source: {source!r}): {parsed}")
        # ignore legacy settings
        parsed.pop("pre_built", None)
        parsed.pop("packages", None)
        # Ensure changelog is correct type
        if "changelog" in parsed and not isinstance(parsed["changelog"], dict):
            parsed["changelog"] = {}
        try:
            return cls(**parsed)
        except Exception as err:
            raise RuntimeError(
                f"failed to load global settings (source: {source!r}): {err}"
            ) from err

    @classmethod
    def from_file(cls, filename: pathlib.Path) -> SettingsFile:
        """Load from file

        Raises :exc:`FileNotFound` when the file is not found.
        The package name is taken from the stem of the file name.
        """
        filename = filename.absolute()
        logger.info("loading settings from %s", filename)
        raw_yaml = filename.read_text(encoding="utf-8")
        return cls.from_string(raw_yaml, source=filename)


class Settings:
    """Settings interface for settings file and package settings"""

    def __init__(
        self,
        *,
        settings: SettingsFile,
        package_settings: typing.Iterable[PackageSettings],
        variant: Variant | str,
        patches_dir: pathlib.Path,
        max_jobs: int | None,
    ) -> None:
        self._settings = settings
        self._package_settings: dict[Package, PackageSettings] = {
            p.name: p for p in package_settings
        }
        self._variant = typing.cast(Variant, variant)
        self._patches_dir = patches_dir
        self._max_jobs = max_jobs
        self._pbi_cache: dict[Package, PackageBuildInfo] = {}

    @classmethod
    def from_files(
        cls,
        *,
        settings_file: pathlib.Path,
        settings_dir: pathlib.Path,
        variant: Variant | str,
        patches_dir: pathlib.Path,
        max_jobs: int | None,
    ) -> Settings:
        """Create Settings from settings.yaml and directory"""
        if settings_file.is_file():
            settings = SettingsFile.from_file(settings_file)
        else:
            logger.debug(
                "settings file %s does not exist, ignoring", settings_file.absolute()
            )
            settings = SettingsFile()
        package_settings = [
            PackageSettings.from_file(package_file)
            for package_file in sorted(settings_dir.glob("*.yaml"))
        ]
        return cls(
            settings=settings,
            package_settings=package_settings,
            variant=variant,
            patches_dir=patches_dir,
            max_jobs=max_jobs,
        )

    @property
    def variant(self) -> Variant:
        """Get current variant"""
        return self._variant

    @variant.setter
    def variant(self, v: Variant) -> None:
        """Change current variant (for testing)"""
        # reset cache
        self._pbi_cache.clear()
        self._variant = v

    @property
    def patches_dir(self) -> pathlib.Path:
        """Get directory with patches"""
        return self._patches_dir

    @patches_dir.setter
    def patches_dir(self, path: pathlib.Path) -> None:
        """Change patches_dir (for testing)"""
        self._pbi_cache.clear()
        self._patches_dir = path

    @property
    def max_jobs(self) -> int | None:
        """Get max parallel jobs"""
        return self._max_jobs

    @max_jobs.setter
    def max_jobs(self, jobs: int | None) -> None:
        """Change max jobs (for testing)"""
        self._pbi_cache.clear()
        self._max_jobs = jobs

    def variant_changelog(self) -> list[str]:
        """Get global changelog for current variant"""
        return list(self._settings.changelog.get(self.variant, []))

    def package_setting(self, package: str | Package) -> PackageSettings:
        """Get package settings for package"""
        package = Package(canonicalize_name(package, validate=True))
        ps = self._package_settings.get(package)
        if ps is None:
            # create and cache default settings
            ps = PackageSettings.from_default(package)
            self._package_settings[package] = ps
        return ps

    def package_build_info(self, package: str | Package) -> PackageBuildInfo:
        """Get (cached) PackageBuildInfo for package and current variant"""
        package = Package(canonicalize_name(package, validate=True))
        pbi = self._pbi_cache.get(package)
        if pbi is None:
            ps = self.package_setting(package)
            pbi = PackageBuildInfo(self, ps)
            self._pbi_cache[package] = pbi
        return pbi

    def list_pre_built(self) -> set[Package]:
        """List packages marked as pre-built"""
        return set(
            name
            for name in self._package_settings
            if self.package_build_info(name).pre_built
        )

    def list_overrides(self) -> set[Package]:
        """List packages with overrides

        - `settings/package.yaml`
        - override plugin
        - `patches/package-version/*.patch`
        """
        packages: set[Package] = set()

        # package settings with a config file
        packages.update(
            ps.name for ps in self._package_settings.values() if ps.has_config
        )

        # override plugins
        exts = overrides._get_extensions()
        packages.update(
            Package(canonicalize_name(name, validate=True)) for name in exts.names()
        )

        # patches
        for patchfile in self.patches_dir.glob("*/*.patch"):
            # parent directory has format "package-version"
            name = patchfile.parent.name.rsplit("-", 1)[0]
            packages.add(Package(canonicalize_name(name, validate=True)))

        return packages

    def all_variants(self) -> set[Variant]:
        """List all variants with overrides"""
        variants: set[Variant] = set()
        # from global settings
        variants.update(self._settings.changelog.keys())
        # from package settings
        for ps in self._package_settings.values():
            variants.update(ps.variants.keys())
        return variants
