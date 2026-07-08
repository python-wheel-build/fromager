from __future__ import annotations

import collections
import datetime
import logging
import os
import pathlib
import shutil
import threading
import typing
from urllib.parse import urlparse

from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version

from . import (
    constraints,
    dependency_graph,
    external_commands,
    packagesettings,
)

if typing.TYPE_CHECKING:
    from . import build_environment, cache, candidate

logger = logging.getLogger(__name__)

# Map package names to (requirement type, dependency name, version)
BuildRequirements = dict[str, list[tuple[str, NormalizedName, Version, Requirement]]]
ROOT_BUILD_REQUIREMENT = canonicalize_name("", validate=False)


class WorkContext:
    def __init__(
        self,
        *,
        active_settings: packagesettings.Settings | None,
        patches_dir: pathlib.Path,
        sdists_repo: pathlib.Path,
        wheels_repo: pathlib.Path,
        work_dir: pathlib.Path,
        constraints_files: tuple[str, ...] = (),
        cleanup: bool = True,
        variant: str = "cpu",
        network_isolation: bool = False,
        max_jobs: int | None = None,
        settings_dir: pathlib.Path | None = None,
        wheel_server_url: str = "",
        cooldown: candidate.Cooldown | None = None,
        max_release_age: datetime.timedelta | None = None,
    ):
        if active_settings is None:
            active_settings = packagesettings.Settings(
                settings=packagesettings.SettingsFile(),
                package_settings=[],
                patches_dir=patches_dir,
                variant=variant,
                max_jobs=max_jobs,
            )
        self.settings = active_settings
        self.sdists_repo = pathlib.Path(sdists_repo).resolve()
        self.sdists_downloads = self.sdists_repo / "downloads"
        self.sdists_builds = self.sdists_repo / "builds"
        self.wheels_repo = pathlib.Path(wheels_repo).resolve()
        self.wheels_build_base = self.wheels_repo / "build"
        self.wheels_downloads = self.wheels_repo / "downloads"
        self.wheels_prebuilt = self.wheels_repo / "prebuilt"
        self.wheel_server_dir = self.wheels_repo / "simple"
        self.work_dir = pathlib.Path(work_dir).resolve()
        self.graph_file = self.work_dir / "graph.json"
        self.merged_constraints = self.work_dir / "merged-constraints.txt"
        self.uv_cache = self.work_dir / "uv-cache"
        self.wheel_server_url = wheel_server_url
        self.logs_dir = self.work_dir / "logs"
        self.cleanup = cleanup
        # separate value so bootstrap-parallel can keep build envs
        self.cleanup_buildenv = cleanup
        self.variant = variant
        self.network_isolation = network_isolation
        self.settings_dir = settings_dir

        self.dependency_graph = dependency_graph.DependencyGraph()

        self.constraints = constraints.Constraints()
        self.input_constraints_files = constraints_files
        for constraints_file in self.input_constraints_files:
            self.constraints.load_constraints_file(constraints_file)

        # storing metrics
        self.time_store: dict[str, dict[str, float]] = collections.defaultdict(
            dict[str, float]
        )
        self.time_description_store: dict[str, str] = {}

        self._parallel_builds = False

        self.cooldown: candidate.Cooldown | None = cooldown
        self._max_release_age: datetime.timedelta | None = max_release_age

        self._cache: cache.CacheManager | None = None

    @property
    def max_release_age(self) -> datetime.timedelta | None:
        return self._max_release_age

    def set_max_release_age(self, days: int) -> None:
        """Set the maximum release age in days."""
        if days < 1:
            raise ValueError(f"max_release_age must be positive, got {days}")
        self._max_release_age = datetime.timedelta(days=days)

    @property
    def cache(self) -> cache.CacheManager | None:
        """The cache manager, if configured."""
        return self._cache

    @cache.setter
    def cache(self, value: cache.CacheManager) -> None:
        self._cache = value

    def enable_parallel_builds(self) -> None:
        self._parallel_builds = True

    @property
    def wheels_build(self) -> pathlib.Path:
        # when parallel builds are enabled, return a path that is unique for the
        # current thread to avoid collisions when creating output files
        if self._parallel_builds:
            thread_path = self.wheels_build_base / f"{threading.get_native_id()}"
            thread_path.mkdir(parents=True, exist_ok=True)
            return thread_path
        else:
            return self.wheels_build_base

    @property
    def pip_wheel_server_args(self) -> list[str]:
        args = ["--index-url", self.wheel_server_url]
        parsed = urlparse(self.wheel_server_url)
        if parsed.scheme != "https" and parsed.hostname:
            args = args + ["--trusted-host", parsed.hostname]
        return args

    @property
    def pip_constraint_args(self) -> list[str]:
        if not self.constraints:
            return []
        return ["--constraint", os.fspath(self.merged_constraints)]

    def uv_clean_cache(self, *reqs: Requirement) -> None:
        """Invalidate and clean uv cache for requirements

        uv caches package metadata and unpacked wheels for faster dependency
        resolution and installation. ``uv pip install`` hardlinks files from
        cache location. This function removes a package from all caches, so
        subsequent installations use a new built.

        'uv clean cache' is concurrency safe since 0.8.19.
        """
        if not reqs:
            raise ValueError("no requirements")

        extra_environ: dict[str, str] = {"UV_CACHE_DIR": str(self.uv_cache)}
        cmd = ["uv", "clean", "cache"]
        req_list: list[str] = sorted(set(req.name for req in reqs))
        logger.debug("invalidate uv cache for %s", req_list)
        cmd.extend(req_list)
        external_commands.run(cmd, extra_environ=extra_environ)

    def write_to_graph_to_file(self) -> None:
        with self.graph_file.open("w", encoding="utf-8") as f:
            self.dependency_graph.serialize(f)

    def package_build_info(
        self, package: str | packagesettings.Package | Requirement
    ) -> packagesettings.PackageBuildInfo:
        if isinstance(package, Requirement):
            name = package.name
        else:
            name = package
        return self.settings.package_build_info(name)

    def setup(self) -> None:
        # The work dir must already exist, so don't try to create it.
        # Use os.makedirs() to create the others in case the paths
        # already exist.
        for p in [
            self.work_dir,
            self.sdists_repo,
            self.sdists_downloads,
            self.sdists_builds,
            self.wheels_repo,
            self.wheels_downloads,
            self.wheels_prebuilt,
            self.wheels_build,
            self.uv_cache,
            self.logs_dir,
        ]:
            if not p.exists():
                logger.debug("creating %s", p)
                p.mkdir(parents=True)
        self.write_constraints()

    def write_constraints(self) -> None:
        """Write combined constraints to disk"""
        if self.constraints:
            with self.merged_constraints.open("w", encoding="utf-8") as f:
                f.write("# auto-generated constraints file\n")
                for constraints_file in self.input_constraints_files:
                    f.write(f"# {constraints_file}\n")
                f.write("\n")
                self.constraints.dump_constraints(f)
            logger.debug(
                "generated %s with content %s",
                self.merged_constraints,
                self.merged_constraints.read_text(),
            )
        else:
            logger.debug("no constraints configured")
            self.merged_constraints.unlink(missing_ok=True)

    def clean_build_dirs(
        self,
        sdist_root_dir: pathlib.Path | None,
        build_env: build_environment.BuildEnvironment | None,
    ) -> None:
        """Cleanup the source tree and build environment

        Leaving any other artifacts that were created.
        """
        if sdist_root_dir and build_env and build_env.path.parent == sdist_root_dir:
            raise ValueError(f"Invalud {sdist_root_dir}, parent of {build_env}")

        if sdist_root_dir and sdist_root_dir.exists():
            if self.cleanup:
                logger.debug(f"cleaning up source tree {sdist_root_dir}")
                shutil.rmtree(sdist_root_dir)
                logger.debug(f"cleaned up source tree {sdist_root_dir}")
            else:
                logger.debug(f"keeping source tree {sdist_root_dir}")

        if build_env and build_env.path.exists():
            if self.cleanup_buildenv:
                logger.debug(f"cleaning up build environment {build_env.path}")
                shutil.rmtree(build_env.path)
                logger.debug(f"cleaned up build environment {build_env.path}")
            else:
                logger.debug(f"keeping build environment {build_env.path}")
