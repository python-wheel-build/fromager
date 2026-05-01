"""PackageBuildInfo class and system resource helpers."""

from __future__ import annotations

import logging
import os
import pathlib
import types
import typing
from collections.abc import Mapping

import psutil
from packaging.utils import BuildTag, NormalizedName
from packaging.version import Version

from .. import overrides
from ._models import (
    GitOptions,
    PackageSettings,
    ProjectOverride,
    PurlConfig,
    VariantInfo,
)
from ._templates import _resolve_template, substitute_template
from ._typedefs import Annotations, PackageVersion, PatchMap, Template, Variant

if typing.TYPE_CHECKING:
    from .. import build_environment
    from ._settings import Settings

logger = logging.getLogger(__name__)


def get_cpu_count() -> int:
    """CPU count from scheduler affinity"""
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    else:
        return os.cpu_count() or 1


def get_available_memory_gib() -> float:
    """available virtual memory in GiB"""
    return psutil.virtual_memory().available / (1024**3)


class PackageBuildInfo:
    """Package build information

    Public API for PackageSettings with i
    """

    def __init__(self, settings: Settings, ps: PackageSettings) -> None:
        self._settings = settings
        self._variant = typing.cast(Variant, settings.variant)
        self._patches_dir = settings.patches_dir
        self._variant_changelog = settings.variant_changelog()
        self._max_jobs: int | None = settings.max_jobs
        self._ps = ps
        self._plugin_module: types.ModuleType | None | typing.Literal[False] = False
        self._patches: PatchMap | None = None
        self._annotations: Annotations | None = None

    @property
    def package(self) -> NormalizedName:
        """Package name"""
        return typing.cast(NormalizedName, self._ps.name)

    @property
    def variant(self) -> Variant:
        """Variant name"""
        return self._variant

    @property
    def purl_config(self) -> PurlConfig | None:
        """Per-package purl configuration for SBOM generation."""
        return self._ps.purl

    @property
    def annotations(self) -> Annotations:
        """Get Package and variant annotations

        Annotations can be used to attach arbitrary metadata to packages and
        package variants. The feature is inspired by Kubernetes's
        annotations. Variant keys have a higher precedence than package keys.

        The prefix ``fromager.`` is reserved for future use by Fromager.

        ::

           annotations:
             "downstream.maintainer": "Platform Team"
           variants:
             cuda:
               annotations:
                 "downstream.maintainer": "CUDA Accelerator Team"
        """
        if self._annotations is None:
            vi = self._ps.variants.get(self.variant)
            va = vi.annotations if vi is not None else None
            self._annotations = Annotations(self._ps.annotations, va)
        return self._annotations

    @property
    def plugin(self) -> types.ModuleType | None:
        """Get Fromager plugin module"""
        if self._plugin_module is False:
            exts = overrides._get_extensions()
            try:
                mod = exts[self.override_module_name].plugin
                self._plugin_module = typing.cast(types.ModuleType, mod)
            except KeyError:
                self._plugin_module = None
        return self._plugin_module

    def get_all_patches(self) -> PatchMap:
        """Get a mapping of version to list of patches"""

        if self._patches is None:
            patches: PatchMap = {}
            version: Version | None

            # Find unversioned and versioned directories (name + '-' + version)
            # with patches for the package.
            dirs_to_scan = []
            unversioned_dir = self._patches_dir / self.override_module_name
            if unversioned_dir.exists():
                dirs_to_scan.append(unversioned_dir)
            versioned_pattern = f"{self.override_module_name}-*"
            dirs_to_scan.extend(self._patches_dir.glob(versioned_pattern))

            prefix_len = len(self.override_module_name) + 1
            for patchdir in dirs_to_scan:
                if patchdir.name == self.override_module_name:
                    version = None
                else:
                    version = Version(patchdir.name[prefix_len:])
                patches[version] = list(patchdir.glob("*.patch"))
                # variant-specific patches
                patches[version].extend(patchdir.joinpath(self.variant).glob("*.patch"))
                patches[version].sort(key=lambda p: p.name)

            self._patches = patches
        return self._patches

    def get_patches(self, version: Version) -> list[pathlib.Path]:
        """Get patches for a version (and unversioned patches)"""
        # ignore local version for patches
        version = Version(version.public)
        patchfiles: list[pathlib.Path] = []
        patchmap = self.get_all_patches()
        # unversioned patches
        patchfiles.extend(patchmap.get(None, []))
        # version-specific patches
        patchfiles.extend(patchmap.get(version, []))
        # sort by basename
        patchfiles.sort(key=lambda p: p.name)
        return patchfiles

    @property
    def has_config(self) -> bool:
        """Does the package have a config file?"""
        return self._ps.has_config

    @property
    def has_customizations(self) -> bool:
        """Does the package have any customizations?"""
        return bool(
            self.has_config or self.plugin is not None or self.get_all_patches()
        )

    @property
    def pre_built(self) -> bool:
        """Does the variant use pre-build wheels?"""
        vi = self._ps.variants.get(self.variant)
        if vi is not None:
            return vi.pre_built
        return False

    @property
    def wheel_server_url(self) -> str | None:
        """Alternative package index for pre-build wheel"""
        vi = self._ps.variants.get(self.variant)
        if vi is not None and vi.wheel_server_url is not None:
            return str(vi.wheel_server_url)
        return None

    @property
    def override_module_name(self) -> str:
        """Override module name from package name"""
        return self._ps.override_module_name

    def download_source_url(
        self,
        version: Version | str | None = None,
        default: str | None = None,
        *,
        resolve_template: bool = True,
    ) -> str | None:
        """sdist download URL"""
        if version is not None and isinstance(version, str):
            version = Version(version)
        template = self._ps.download_source.url
        if template is None and default:
            template = typing.cast(Template, default)
        if template and resolve_template:
            return _resolve_template(template, self.package, version)
        elif template:
            return str(template)
        else:
            return None

    def download_source_destination_filename(
        self,
        version: Version | str | None = None,
        default: str | None = None,
        *,
        resolve_template: bool = True,
    ) -> str | None:
        """Rename sdist to dest filename"""
        if version is not None and isinstance(version, str):
            version = Version(version)
        template = self._ps.download_source.destination_filename
        if template is None and default:
            template = typing.cast(Template, default)
        if template and resolve_template:
            return _resolve_template(template, self.package, version)
        elif template:
            return str(template)
        else:
            return None

    def resolver_sdist_server_url(self, default: str) -> str:
        """Package index server URL for resolving package versions"""
        url = self._ps.resolver_dist.sdist_server_url
        if url is None:
            url = default
        return url

    @property
    def resolver_include_wheels(self) -> bool:
        """Include wheels when resolving package versions?"""
        return self._ps.resolver_dist.include_wheels

    @property
    def resolver_include_sdists(self) -> bool:
        """Include sdists when resolving package versions?"""
        return self._ps.resolver_dist.include_sdists

    @property
    def resolver_ignore_platform(self) -> bool:
        """Ignore the platform when resolving with wheels?"""
        return self._ps.resolver_dist.ignore_platform

    @property
    def resolver_min_release_age(self) -> int | None:
        """Per-package release-age cooldown override in days.

        Returns None (inherit global), 0 (disabled), or a positive integer
        (override days). The caller is responsible for converting to a
        :class:`~fromager.context.Cooldown` instance.
        """
        return self._ps.resolver_dist.min_release_age

    @property
    def use_pypi_org_metadata(self) -> bool:
        """Can use metadata from pypi.org JSON / Simple API?

        By default, packages with customizations do not use public
        pypi.org metadata.
        """
        ps = self._ps
        flag = ps.resolver_dist.use_pypi_org_metadata
        if flag is not None:
            # flag is set
            return flag
        # return True if package does not have any customizations
        return not self.has_customizations

    def build_dir(self, sdist_root_dir: pathlib.Path) -> pathlib.Path:
        """Build directory for package (e.g. subdirectory)"""
        build_dir = self._ps.build_dir
        if build_dir is not None:
            # ensure that absolute build_dir path from settings is converted to a relative path
            relative_build_dir = build_dir.relative_to(build_dir.anchor)
            return sdist_root_dir / relative_build_dir
        return sdist_root_dir

    def get_changelog(self, version: Version) -> list[str]:
        """Get changelog for a version"""
        # ignore local version for changelog entries
        version = Version(version.public)
        pv = typing.cast(PackageVersion, version)
        variant_changelog = self._variant_changelog
        package_changelog = self._ps.changelog.get(pv, [])
        return variant_changelog + package_changelog

    def build_tag(self, version: Version) -> BuildTag:
        """Build tag for version's changelog and dependencies

        The build tag is calculated as:
            own_changelog_count + sum(dependency_build_tags)

        Dependencies are resolved recursively and transitively.

        Args:
            version: Package version to calculate build tag for

        Raises:
            ValueError: If circular dependency detected

        .. versionchanged 0.54.0::

           Fromager ignores local version suffix of a package to determinate
           the build tag from changelog, e.g. version `1.0.3+local.suffix`
           uses `1.0.3`.
        """
        return self._calculate_build_tag(version, visited=set())

    def _calculate_build_tag(
        self, version: Version, visited: set[NormalizedName]
    ) -> BuildTag:
        """Recursively calculate build tag including dependencies

        Args:
            version: Package version to calculate build tag for
            visited: Set of already-visited packages for cycle detection

        Raises:
            ValueError: If circular dependency detected
        """
        if self.pre_built:
            # pre-built wheels have no built tag
            return ()

        # Check for circular dependency
        if self.package in visited:
            raise ValueError(
                f"Circular dependency detected: {self.package} appears in "
                f"dependency chain: {' -> '.join(sorted(visited))} -> {self.package}"
            )

        # Add current package to visited set (immutable update)
        visited = visited | {self.package}

        # Calculate own changelog count
        pv = typing.cast(PackageVersion, version)
        own_changelog_count = len(self.get_changelog(pv))

        # Calculate dependency contribution
        dependency_contribution = 0
        for dep_pkg in self._ps.dependencies:
            dep_pbi = self._settings.package_build_info(dep_pkg)
            dep_tag = dep_pbi._calculate_build_tag(version, visited=visited)
            if dep_tag:  # Only count if dependency has a build tag
                dependency_contribution += dep_tag[0]

        total = own_changelog_count + dependency_contribution

        if total == 0:
            return ()

        suffix = ""
        return total, suffix

    def get_extra_environ(
        self,
        *,
        template_env: dict[str, str] | None = None,
        build_env: build_environment.BuildEnvironment | None = None,
        version: Version | None = None,
    ) -> dict[str, str]:
        """Get extra environment variables for a variant

        1. parallel jobs: ``MAKEFLAGS``, ``MAX_JOBS``, ``CMAKE_BUILD_PARALLEL_LEVEL``
        2. PATH and VIRTUAL_ENV from ``build_env`` (if given)
        3. package's env settings
        4. package variant's env settings

        `template_env` defaults to `os.environ`.
        """
        if template_env is None:
            template_env = os.environ.copy()
        else:
            template_env = template_env.copy()

        if version is not None:
            template_env["__version__"] = str(version)
        else:
            # Prevent a stray __version__ in os.environ from being
            # silently used when the real version is unknown.
            template_env.pop("__version__", None)

        # configure max jobs settings, settings depend on package, available
        # CPU cores, and available virtual memory.
        jobs = self.parallel_jobs()
        extra_environ: dict[str, str] = {
            "MAKEFLAGS": f"{template_env.get('MAKEFLAGS', '')} -j{jobs}".strip(),
            "CMAKE_BUILD_PARALLEL_LEVEL": str(jobs),
            "MAX_JOBS": str(jobs),
        }

        # make MAX_JOBS available to substitution
        template_env.update(extra_environ)

        # add VIRTUAL_ENV and update PATH, so templates can use the values
        if build_env is not None:
            venv_environ = build_env.get_venv_environ(template_env=template_env)
            template_env.update(venv_environ)
            extra_environ.update(venv_environ)

        # chain entries so variant entries can reference general entries
        entries = list(self._ps.env.items())
        vi = self._ps.variants.get(self.variant)
        if vi is not None:
            entries.extend(vi.env.items())

        for key, value in entries:
            value = substitute_template(value, template_env)
            extra_environ[key] = value
            # subsequent key-value pairs can depend on previously vars.
            template_env[key] = value

        return extra_environ

    def parallel_jobs(self) -> int:
        """How many parallel jobs?"""
        # adjust by CPU cores, at least 1
        cpu_cores_per_job = self._ps.build_options.cpu_cores_per_job
        cpu_count = get_cpu_count()
        max_num_job_cores = int(max(1, cpu_count // cpu_cores_per_job))
        logger.debug(
            f"{self.package}: {max_num_job_cores=}, {cpu_cores_per_job=}, {cpu_count=}"
        )

        # adjust by memory consumption per job, at least 1
        memory_per_job_gb = self._ps.build_options.memory_per_job_gb
        free_memory = get_available_memory_gib()
        max_num_jobs_memory = int(max(1.0, free_memory // memory_per_job_gb))
        logger.debug(
            f"{self.package}: {max_num_jobs_memory=}, {memory_per_job_gb=}, {free_memory=:0.1f} GiB"
        )

        # limit by smallest amount of CPU, memory, and --jobs parameter
        max_jobs = cpu_count if self._max_jobs is None else self._max_jobs
        parallel_builds = min(max_num_job_cores, max_num_jobs_memory, max_jobs)

        logger.debug(
            f"{self.package}: parallel builds {parallel_builds=} "
            f"({free_memory=:0.1f} GiB, {cpu_count=}, {max_jobs=})"
        )

        return parallel_builds

    @property
    def build_ext_parallel(self) -> bool:
        """Configure [build_ext]parallel for setuptools?"""
        return self._ps.build_options.build_ext_parallel

    @property
    def config_settings(self) -> dict[str, str | list[str]]:
        return self._ps.config_settings

    @property
    def git_options(self) -> GitOptions:
        """Git repository cloning options"""
        return self._ps.git_options

    @property
    def project_override(self) -> ProjectOverride:
        return self._ps.project_override

    @property
    def exclusive_build(self) -> bool:
        return self._ps.build_options.exclusive_build

    @property
    def variants(self) -> Mapping[Variant, VariantInfo]:
        """Get the variant configuration for the current package"""
        return self._ps.variants

    def serialize(self, **kwargs: typing.Any) -> dict[str, typing.Any]:
        return self._ps.serialize(**kwargs)
