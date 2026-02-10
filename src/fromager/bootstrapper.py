"""Bootstrap orchestration for building Python packages from source.

This module provides the Bootstrapper class which orchestrates the entire
bootstrap process, including:
- Dependency tracking and build ordering
- Building wheels and sdists from source
- Managing the dependency graph
- Test mode for catching and reporting failures

The resolution logic (determining which version to use for a requirement)
is delegated to the ResolutionManager class, following the Single
Responsibility Principle.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import json
import logging
import operator
import pathlib
import typing

from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version

from . import (
    build_environment,
    dependencies,
    finders,
    hooks,
    progress,
    server,
    sources,
    wheels,
)
from .dependency_graph import DependencyGraph
from .log import req_ctxvar_context
from .requirements_file import RequirementType, SourceType
from .resolution_manager import ResolutionManager

if typing.TYPE_CHECKING:
    from . import context

logger = logging.getLogger(__name__)

# package name, extras, version, sdist/wheel
SeenKey = tuple[NormalizedName, tuple[str, ...], str, typing.Literal["sdist", "wheel"]]


@dataclasses.dataclass
class SourceBuildResult:
    """Result of building a package from source.

    Used to return multiple values from _build_from_source().
    """

    wheel_filename: pathlib.Path | None
    sdist_filename: pathlib.Path | None
    unpack_dir: pathlib.Path
    sdist_root_dir: pathlib.Path | None
    build_env: build_environment.BuildEnvironment | None
    source_type: SourceType


# Valid failure types for test mode error recording
FailureType = typing.Literal["resolution", "bootstrap", "hook", "dependency_extraction"]


class FailureRecord(typing.TypedDict):
    """Record of a package that failed during bootstrap in test mode.

    Attributes:
        package: The package name that failed.
        version: The resolved version (None if resolution failed).
        exception_type: The exception class name.
        exception_message: The exception message string.
        failure_type: Category of failure for analysis.
    """

    package: str
    version: str | None
    exception_type: str
    exception_message: str
    failure_type: FailureType


class Bootstrapper:
    """Orchestrates the bootstrap process for building packages from source.

    The Bootstrapper handles the overall workflow of building Python packages
    and their dependencies. It delegates version resolution to the
    ResolutionManager class and focuses on:

    - Managing the build order and dependency tracking
    - Building sdists and wheels from source
    - Handling pre-built wheels
    - Updating the dependency graph
    - Test mode error handling and reporting

    Attributes:
        ctx: The work context for this bootstrap run.
        progressbar: Progress indicator for the bootstrap process.
        prev_graph: Optional dependency graph from a previous run.
        cache_wheel_server_url: URL to check for pre-built wheels.
        sdist_only: If True, only build sdists (not wheels) for non-build deps.
        test_mode: If True, continue on errors and report at end.
        why: Stack tracking the current dependency chain.
        resolver: The ResolutionManager instance for version resolution.
    """

    def __init__(
        self,
        ctx: context.WorkContext,
        progressbar: progress.Progressbar | None = None,
        prev_graph: DependencyGraph | None = None,
        cache_wheel_server_url: str | None = None,
        sdist_only: bool = False,
        test_mode: bool = False,
    ) -> None:
        """Initialize the bootstrapper.

        Args:
            ctx: The work context for this bootstrap run.
            progressbar: Optional progress indicator.
            prev_graph: Optional dependency graph from a previous run for
                history-based resolution.
            cache_wheel_server_url: URL of a wheel server to check for
                pre-built wheels.
            sdist_only: If True, only build sdists for non-build dependencies.
            test_mode: If True, continue processing after failures and report
                at end instead of failing immediately.

        Raises:
            ValueError: If both test_mode and sdist_only are True.
        """
        if test_mode and sdist_only:
            raise ValueError(
                "--test-mode requires full wheel builds; incompatible with --sdist-only"
            )

        self.ctx = ctx
        self.progressbar = progressbar or progress.Progressbar(None)
        self.prev_graph = prev_graph
        self.cache_wheel_server_url = cache_wheel_server_url or ctx.wheel_server_url
        self.sdist_only = sdist_only
        self.test_mode = test_mode

        # Stack tracking the current dependency chain. Each entry is
        # (req_type, requirement, version). Used for logging and graph-based
        # resolution to determine the parent of a dependency.
        self.why: list[tuple[RequirementType, Requirement, Version]] = []

        # Push items onto the stack as we start to resolve their
        # dependencies so at the end we have a list of items that need to
        # be built in order.
        self._build_stack: list[typing.Any] = []
        self._build_requirements: set[tuple[NormalizedName, str]] = set()

        # Track requirements we've seen before so we don't resolve the
        # same dependencies over and over and so we can break cycles in
        # the dependency list. The key is the requirements spec, rather
        # than the package, in case we do have multiple rules for the same
        # package.
        self._seen_requirements: set[SeenKey] = set()

        self._build_order_filename = self.ctx.work_dir / "build-order.json"

        # Track failed packages in test mode (list of typed dicts for JSON export)
        self.failed_packages: list[FailureRecord] = []

        # Create the resolution manager with a callback for preparing build
        # dependencies. This is needed when resolving git URLs where we need
        # to build the project to get the version from metadata.
        self.resolver = ResolutionManager(
            ctx=ctx,
            prev_graph=prev_graph,
            cache_wheel_server_url=self.cache_wheel_server_url,
            prepare_build_deps_callback=self._prepare_build_dependencies,
        )

    def resolve_and_add_top_level(
        self,
        req: Requirement,
    ) -> tuple[str, Version] | None:
        """Resolve a top-level requirement and add it to the dependency graph.

        This is the pre-resolution phase before recursive bootstrapping begins.
        In test mode, catches resolution errors and records them as failures.

        Args:
            req: The top-level requirement to resolve.

        Returns:
            Tuple of (source_url, version) if resolution succeeded, None if it
            failed in test mode.

        Raises:
            Exception: In normal mode, re-raises any resolution error.
        """
        try:
            pbi = self.ctx.package_build_info(req)
            source_url, version = self.resolve_version(
                req=req,
                req_type=RequirementType.TOP_LEVEL,
            )
            logger.info("%s resolves to %s", req, version)
            self.ctx.dependency_graph.add_dependency(
                parent_name=None,
                parent_version=None,
                req_type=RequirementType.TOP_LEVEL,
                req=req,
                req_version=version,
                download_url=source_url,
                pre_built=pbi.pre_built,
                constraint=self.ctx.constraints.get_constraint(req.name),
            )
            return (source_url, version)
        except Exception as err:
            if not self.test_mode:
                raise
            self._record_test_mode_failure(req, None, err, "resolution")
            return None

    def resolve_version(
        self,
        req: Requirement,
        req_type: RequirementType,
    ) -> tuple[str, Version]:
        """Resolve the version of a requirement.

        Delegates to the ResolutionManager, passing the current dependency
        chain (why stack) for context in history-based resolution.

        Args:
            req: The requirement to resolve.
            req_type: The type of requirement (top-level, install, build, etc.)

        Returns:
            Tuple of (source_url, version) where source_url is the download URL
            for the source or wheel.
        """
        return self.resolver.resolve_version(req, req_type, why=self.why)

    def _processing_build_requirement(self, current_req_type: RequirementType) -> bool:
        """Are we currently processing a build requirement?

        We determine that a package is a build dependency if its requirement
        type is build_system, build_backend, or build_sdist OR if it is an
        installation requirement of something that is a build dependency. We
        use a verbose loop to determine the status so we can log the reason
        something is treated as a build dependency.
        """
        if current_req_type.is_build_requirement:
            logger.debug(f"is itself a build requirement: {current_req_type}")
            return True
        if not current_req_type.is_install_requirement:
            logger.debug(
                "is not an install requirement, not checking dependency chain for a build requirement"
            )
            return False
        for req_type, req, resolved_version in reversed(self.why):
            if req_type.is_build_requirement:
                logger.debug(
                    f"is a build requirement because {req_type} dependency {req} ({resolved_version}) depends on it"
                )
                return True
        logger.debug("is not a build requirement")
        return False

    def bootstrap(self, req: Requirement, req_type: RequirementType) -> None:
        """Bootstrap a package and its dependencies.

        Handles setup, validation, and error handling. Delegates actual build
        work to _bootstrap_impl().

        In test mode, catches build exceptions, records package name, and continues.
        In normal mode, raises exceptions immediately (fail-fast).
        """
        logger.info(f"bootstrapping {req} as {req_type} dependency of {self.why[-1:]}")

        # Resolve version first so we have it for error reporting.
        # In test mode, record resolution failures and continue.
        try:
            source_url, resolved_version = self.resolve_version(
                req=req,
                req_type=req_type,
            )
        except Exception as err:
            if not self.test_mode:
                raise
            self._record_test_mode_failure(req, None, err, "resolution")
            return

        # Capture parent before _track_why pushes current package onto the stack
        parent: tuple[Requirement, Version] | None = None
        if self.why:
            _, parent_req, parent_version = self.why[-1]
            parent = (parent_req, parent_version)

        # Update dependency graph unconditionally (before seen check to capture all edges)
        self._add_to_graph(req, req_type, resolved_version, source_url, parent)

        # Build sdist-only (no wheel) if flag is set, unless this is a build
        # requirement which always needs a full wheel.
        build_sdist_only = self.sdist_only and not self._processing_build_requirement(
            req_type
        )

        # Avoid cyclic dependencies and redundant processing.
        if self._has_been_seen(req, resolved_version, build_sdist_only):
            logger.debug(
                f"redundant {req_type} dependency {req} "
                f"({resolved_version}, sdist_only={build_sdist_only}) for {self._explain}"
            )
            return
        self._mark_as_seen(req, resolved_version, build_sdist_only)

        logger.info(f"new {req_type} dependency {req} resolves to {resolved_version}")

        # Track dependency chain - context manager ensures cleanup even on exception
        with self._track_why(req_type, req, resolved_version):
            try:
                self._bootstrap_impl(
                    req, req_type, source_url, resolved_version, build_sdist_only
                )
            except Exception as err:
                if not self.test_mode:
                    raise
                self._record_test_mode_failure(
                    req, str(resolved_version), err, "bootstrap"
                )

    def _bootstrap_impl(
        self,
        req: Requirement,
        req_type: RequirementType,
        source_url: str,
        resolved_version: Version,
        build_sdist_only: bool,
    ) -> None:
        """Internal implementation - performs the actual bootstrap work.

        Called by bootstrap() after setup, validation, and seen-checking.

        Args:
            req: The requirement to bootstrap.
            req_type: The type of requirement.
            source_url: The resolved source URL.
            resolved_version: The resolved version.
            build_sdist_only: Whether to build only sdist (no wheel).

        Error Handling:
            Fatal errors (source build, prebuilt download) raise exceptions
            for bootstrap() to catch and record.

            Non-fatal errors (post-hook, dependency extraction) are recorded
            locally and processing continues. These are recorded here because
            the package build succeeded - only optional post-processing failed.
        """
        constraint = self.ctx.constraints.get_constraint(req.name)
        if constraint:
            logger.info(
                f"incoming requirement {req} matches constraint {constraint}. Will apply both."
            )

        pbi = self.ctx.package_build_info(req)

        cached_wheel_filename: pathlib.Path | None = None
        unpacked_cached_wheel: pathlib.Path | None = None

        if pbi.pre_built:
            wheel_filename, unpack_dir = self._download_prebuilt(
                req=req,
                req_type=req_type,
                resolved_version=resolved_version,
                wheel_url=source_url,
            )
            build_result = SourceBuildResult(
                wheel_filename=wheel_filename,
                sdist_filename=None,
                unpack_dir=unpack_dir,
                sdist_root_dir=None,
                build_env=None,
                source_type=SourceType.PREBUILT,
            )
        else:
            # Look for an existing wheel in caches before building
            cached_wheel_filename, unpacked_cached_wheel = self._find_cached_wheel(
                req, resolved_version
            )

            # Build from source (handles test-mode fallback internally)
            build_result = self._build_from_source(
                req=req,
                resolved_version=resolved_version,
                source_url=source_url,
                req_type=req_type,
                build_sdist_only=build_sdist_only,
                cached_wheel_filename=cached_wheel_filename,
                unpacked_cached_wheel=unpacked_cached_wheel,
            )

        # Run post-bootstrap hooks (non-fatal in test mode)
        try:
            hooks.run_post_bootstrap_hooks(
                ctx=self.ctx,
                req=req,
                dist_name=canonicalize_name(req.name),
                dist_version=str(resolved_version),
                sdist_filename=build_result.sdist_filename,
                wheel_filename=build_result.wheel_filename,
            )
        except Exception as hook_error:
            if not self.test_mode:
                raise
            self._record_test_mode_failure(
                req, str(resolved_version), hook_error, "hook", "warning"
            )

        # Extract install dependencies (non-fatal in test mode)
        try:
            install_dependencies = self._get_install_dependencies(
                req=req,
                resolved_version=resolved_version,
                wheel_filename=build_result.wheel_filename,
                sdist_filename=build_result.sdist_filename,
                sdist_root_dir=build_result.sdist_root_dir,
                build_env=build_result.build_env,
                unpack_dir=build_result.unpack_dir,
            )
        except Exception as dep_error:
            if not self.test_mode:
                raise
            self._record_test_mode_failure(
                req,
                str(resolved_version),
                dep_error,
                "dependency_extraction",
                "warning",
            )
            install_dependencies = []

        logger.debug(
            "install dependencies: %s",
            ", ".join(sorted(str(r) for r in install_dependencies)),
        )

        self._add_to_build_order(
            req=req,
            version=resolved_version,
            source_url=source_url,
            source_type=build_result.source_type,
            prebuilt=pbi.pre_built,
            constraint=constraint,
        )

        self.progressbar.update_total(len(install_dependencies))
        for dep in self._sort_requirements(install_dependencies):
            with req_ctxvar_context(dep):
                # In test mode, bootstrap() catches and records failures internally.
                # In normal mode, it raises immediately which we propagate.
                self.bootstrap(req=dep, req_type=RequirementType.INSTALL)
            self.progressbar.update()

        # Clean up build directories
        self.ctx.clean_build_dirs(build_result.sdist_root_dir, build_result.build_env)

    @contextlib.contextmanager
    def _track_why(
        self,
        req_type: RequirementType,
        req: Requirement,
        resolved_version: Version,
    ) -> typing.Generator[None, None, None]:
        """Context manager to track dependency chain in self.why stack.

        Ensures the entry is always popped from the stack, even if an
        exception occurs during processing. This prevents stack corruption.
        """
        self.why.append((req_type, req, resolved_version))
        try:
            yield
        finally:
            self.why.pop()

    def _record_test_mode_failure(
        self,
        req: Requirement,
        version: str | None,
        err: Exception,
        failure_type: FailureType,
        log_level: typing.Literal["error", "warning"] = "error",
    ) -> None:
        """Record a failure in test mode. Call this after checking test_mode.

        Args:
            req: The requirement that failed.
            version: The version being processed (None if not yet resolved).
            err: The exception that was raised.
            failure_type: Category of failure for analysis.
            log_level: Log at error (fatal) or warning (non-fatal, continuing).
        """
        version_str = f"=={version}" if version else ""
        msg = f"test mode: {failure_type} failed for {req.name}{version_str}"
        if log_level == "warning":
            logger.warning("%s: %s (continuing)", msg, err)
        else:
            logger.error("%s: %s", msg, err, exc_info=True)

        self.failed_packages.append(
            {
                "package": str(req.name),
                "version": version,
                "exception_type": err.__class__.__name__,
                "exception_message": str(err),
                "failure_type": failure_type,
            }
        )

    @property
    def _explain(self) -> str:
        """Return message formatting current version of why stack."""
        return " for ".join(
            f"{req_type} dependency {req} ({resolved_version})"
            for req_type, req, resolved_version in reversed(self.why)
        )

    def _build_sdist(
        self,
        req: Requirement,
        resolved_version: Version,
        sdist_root_dir: pathlib.Path,
        build_env: build_environment.BuildEnvironment,
    ) -> pathlib.Path:
        find_sdist_result = finders.find_sdist(
            self.ctx, self.ctx.sdists_builds, req, str(resolved_version)
        )
        if not find_sdist_result:
            sdist_filename: pathlib.Path = sources.build_sdist(
                ctx=self.ctx,
                req=req,
                version=resolved_version,
                sdist_root_dir=sdist_root_dir,
                build_env=build_env,
            )
        else:
            sdist_filename = find_sdist_result
            logger.info(f"have sdist version {resolved_version}: {find_sdist_result}")
        return sdist_filename

    def _build_wheel(
        self,
        req: Requirement,
        resolved_version: Version,
        sdist_root_dir: pathlib.Path,
        build_env: build_environment.BuildEnvironment,
    ) -> tuple[pathlib.Path, pathlib.Path]:
        sdist_filename = self._build_sdist(
            req, resolved_version, sdist_root_dir, build_env
        )

        logger.info(f"starting build of {self._explain} for {self.ctx.variant}")
        built_filename = wheels.build_wheel(
            ctx=self.ctx,
            req=req,
            sdist_root_dir=sdist_root_dir,
            version=resolved_version,
            build_env=build_env,
        )
        server.update_wheel_mirror(self.ctx)
        # When we update the mirror, the built file moves to the
        # downloads directory.
        wheel_filename = self.ctx.wheels_downloads / built_filename.name
        logger.info(f"built wheel for version {resolved_version}: {wheel_filename}")
        return wheel_filename, sdist_filename

    def _prepare_build_dependencies(
        self,
        req: Requirement,
        sdist_root_dir: pathlib.Path,
        build_env: build_environment.BuildEnvironment,
    ) -> set[Requirement]:
        # build system
        build_system_dependencies = dependencies.get_build_system_dependencies(
            ctx=self.ctx,
            req=req,
            sdist_root_dir=sdist_root_dir,
        )
        self._handle_build_requirements(
            req,
            RequirementType.BUILD_SYSTEM,
            build_system_dependencies,
        )
        # The next hooks need build system requirements.
        build_env.install(build_system_dependencies)

        # build backend
        build_backend_dependencies = dependencies.get_build_backend_dependencies(
            ctx=self.ctx,
            req=req,
            sdist_root_dir=sdist_root_dir,
            build_env=build_env,
        )
        self._handle_build_requirements(
            req,
            RequirementType.BUILD_BACKEND,
            build_backend_dependencies,
        )

        # build sdist
        build_sdist_dependencies = dependencies.get_build_sdist_dependencies(
            ctx=self.ctx,
            req=req,
            sdist_root_dir=sdist_root_dir,
            build_env=build_env,
        )
        self._handle_build_requirements(
            req,
            RequirementType.BUILD_SDIST,
            build_sdist_dependencies,
        )

        build_dependencies = build_sdist_dependencies | build_backend_dependencies
        if build_dependencies.isdisjoint(build_system_dependencies):
            build_env.install(build_dependencies)

        return (
            build_system_dependencies
            | build_backend_dependencies
            | build_sdist_dependencies
        )

    def _handle_build_requirements(
        self,
        req: Requirement,
        build_type: RequirementType,
        build_dependencies: set[Requirement],
    ) -> None:
        self.progressbar.update_total(len(build_dependencies))

        for dep in self._sort_requirements(build_dependencies):
            with req_ctxvar_context(dep):
                # In test mode, bootstrap() catches and records failures internally.
                # In normal mode, it raises immediately which we propagate.
                self.bootstrap(req=dep, req_type=build_type)
            self.progressbar.update()

    def _download_prebuilt(
        self,
        req: Requirement,
        req_type: RequirementType,
        resolved_version: Version,
        wheel_url: str,
    ) -> tuple[pathlib.Path, pathlib.Path]:
        """Download a pre-built wheel.

        Args:
            req: The requirement to download.
            req_type: The type of requirement.
            resolved_version: The version to download.
            wheel_url: URL to download the wheel from.

        Returns:
            Tuple of (wheel_filename, unpack_dir).
        """
        logger.info(f"{req_type} requirement {req} uses a pre-built wheel")

        wheel_filename = wheels.download_wheel(req, wheel_url, self.ctx.wheels_prebuilt)
        unpack_dir = self.resolver.create_unpack_dir(req, resolved_version)
        # Update the wheel mirror so pre-built wheels are indexed
        # and available to subsequent builds that need them as dependencies
        server.update_wheel_mirror(self.ctx)
        return (wheel_filename, unpack_dir)

    def _find_cached_wheel(
        self,
        req: Requirement,
        resolved_version: Version,
    ) -> tuple[pathlib.Path | None, pathlib.Path | None]:
        """Look for cached wheel in multiple locations.

        Delegates to the ResolutionManager which checks:
        1. wheels_build directory (previously built)
        2. wheels_downloads directory (previously downloaded)
        3. Cache server (remote cache)

        Args:
            req: The requirement to find a wheel for.
            resolved_version: The specific version to look for.

        Returns:
            Tuple of (cached_wheel_filename, unpacked_cached_wheel).
            Both None if no cache hit.
        """
        return self.resolver.find_cached_wheel(req, resolved_version)

    def _get_install_dependencies(
        self,
        req: Requirement,
        resolved_version: Version,
        wheel_filename: pathlib.Path | None,
        sdist_filename: pathlib.Path | None,
        sdist_root_dir: pathlib.Path | None,
        build_env: build_environment.BuildEnvironment | None,
        unpack_dir: pathlib.Path | None,
    ) -> list[Requirement]:
        """Extract install dependencies from wheel or sdist.

        Returns:
            List of install requirements.

        Raises:
            RuntimeError: If both wheel_filename and sdist_filename are None.
        """
        if wheel_filename is not None:
            assert unpack_dir is not None
            logger.debug(
                "get install dependencies of wheel %s",
                wheel_filename.name,
            )
            return list(
                dependencies.get_install_dependencies_of_wheel(
                    req=req,
                    wheel_filename=wheel_filename,
                    requirements_file_dir=unpack_dir,
                )
            )
        elif sdist_filename is not None:
            assert sdist_root_dir is not None
            assert build_env is not None
            logger.debug(
                "get install dependencies of sdist from directory %s",
                sdist_root_dir,
            )
            return list(
                dependencies.get_install_dependencies_of_sdist(
                    ctx=self.ctx,
                    req=req,
                    version=resolved_version,
                    sdist_root_dir=sdist_root_dir,
                    build_env=build_env,
                )
            )
        else:
            raise RuntimeError("wheel_filename and sdist_filename are None")

    def _download_source(
        self,
        req: Requirement,
        resolved_version: Version,
        source_url: str,
    ) -> pathlib.Path:
        """Download source for a package."""
        result: pathlib.Path = sources.download_source(
            ctx=self.ctx,
            req=req,
            version=resolved_version,
            download_url=source_url,
        )
        return result

    def _prepare_source(
        self,
        req: Requirement,
        resolved_version: Version,
        source_filename: pathlib.Path,
    ) -> pathlib.Path:
        """Prepare (unpack/patch) source for building."""
        result: pathlib.Path = sources.prepare_source(
            ctx=self.ctx,
            req=req,
            source_filename=source_filename,
            version=resolved_version,
        )
        return result

    def _create_build_env(
        self,
        req: Requirement,
        resolved_version: Version,
        parent_dir: pathlib.Path,
    ) -> build_environment.BuildEnvironment:
        """Create isolated build environment."""
        return build_environment.BuildEnvironment(
            ctx=self.ctx,
            parent_dir=parent_dir,
        )

    def _do_build(
        self,
        req: Requirement,
        resolved_version: Version,
        sdist_root_dir: pathlib.Path,
        build_env: build_environment.BuildEnvironment,
        build_sdist_only: bool,
        cached_wheel_filename: pathlib.Path | None,
    ) -> tuple[pathlib.Path | None, pathlib.Path | None]:
        """Build wheel or sdist from prepared source."""
        if cached_wheel_filename:
            logger.debug(
                f"getting install requirements from cached wheel {cached_wheel_filename.name}"
            )
            return cached_wheel_filename, None
        elif build_sdist_only:
            logger.debug(
                f"getting install requirements from sdist {req.name}=={resolved_version}"
            )
            return None, self._build_sdist(
                req, resolved_version, sdist_root_dir, build_env
            )
        else:
            logger.debug(
                f"building wheel {req.name}=={resolved_version} to get install requirements"
            )
            return self._build_wheel(req, resolved_version, sdist_root_dir, build_env)

    def _build_from_source(
        self,
        req: Requirement,
        resolved_version: Version,
        source_url: str,
        req_type: RequirementType,
        build_sdist_only: bool,
        cached_wheel_filename: pathlib.Path | None,
        unpacked_cached_wheel: pathlib.Path | None,
    ) -> SourceBuildResult:
        """Build package from source.

        Orchestrates download, preparation, build environment setup, and build.
        In test mode, attempts pre-built fallback on failure.

        Raises:
            Exception: In normal mode, if build fails.
                In test mode, only if build fails AND fallback also fails.
        """
        try:
            # Download and prepare source (if no cached wheel)
            if not unpacked_cached_wheel:
                logger.debug("no cached wheel, downloading sources")
                source_filename = self._download_source(
                    req=req,
                    resolved_version=resolved_version,
                    source_url=source_url,
                )
                sdist_root_dir = self._prepare_source(
                    req=req,
                    resolved_version=resolved_version,
                    source_filename=source_filename,
                )
            else:
                logger.debug(f"have cached wheel in {unpacked_cached_wheel}")
                sdist_root_dir = unpacked_cached_wheel / unpacked_cached_wheel.stem

            assert sdist_root_dir is not None

            if sdist_root_dir.parent.parent != self.ctx.work_dir:
                raise ValueError(
                    f"'{sdist_root_dir}/../..' should be {self.ctx.work_dir}"
                )
            unpack_dir = sdist_root_dir.parent

            build_env = self._create_build_env(
                req=req,
                resolved_version=resolved_version,
                parent_dir=sdist_root_dir.parent,
            )

            # Prepare build dependencies (always needed)
            # Note: This may recursively call bootstrap() for build deps,
            # which has its own error handling.
            self._prepare_build_dependencies(req, sdist_root_dir, build_env)

            # Build wheel or sdist
            wheel_filename, sdist_filename = self._do_build(
                req=req,
                resolved_version=resolved_version,
                sdist_root_dir=sdist_root_dir,
                build_env=build_env,
                build_sdist_only=build_sdist_only,
                cached_wheel_filename=cached_wheel_filename,
            )

            source_type = sources.get_source_type(self.ctx, req)

            return SourceBuildResult(
                wheel_filename=wheel_filename,
                sdist_filename=sdist_filename,
                unpack_dir=unpack_dir,
                sdist_root_dir=sdist_root_dir,
                build_env=build_env,
                source_type=source_type,
            )

        except Exception as build_error:
            if not self.test_mode:
                raise

            # Test mode: attempt pre-built fallback
            fallback_result = self._handle_test_mode_failure(
                req=req,
                resolved_version=resolved_version,
                req_type=req_type,
                build_error=build_error,
            )
            if fallback_result is None:
                # Fallback failed, re-raise for bootstrap() to catch
                raise

            return fallback_result

    def _handle_test_mode_failure(
        self,
        req: Requirement,
        resolved_version: Version,
        req_type: RequirementType,
        build_error: Exception,
    ) -> SourceBuildResult | None:
        """Handle build failure in test mode by attempting pre-built fallback.

        Args:
            req: The requirement that failed to build.
            resolved_version: The version that was attempted.
            req_type: The type of requirement (for fallback resolution).
            build_error: The original exception from the build attempt.

        Returns:
            SourceBuildResult if fallback succeeded, None if fallback also failed.
        """
        logger.warning(
            "test mode: build failed for %s==%s, attempting pre-built fallback: %s",
            req.name,
            resolved_version,
            build_error,
        )

        try:
            wheel_url, fallback_version = self._resolve_prebuilt_with_history(
                req=req,
                req_type=req_type,
            )

            if fallback_version != resolved_version:
                logger.warning(
                    "test mode: version mismatch for %s - requested %s, fallback %s",
                    req.name,
                    resolved_version,
                    fallback_version,
                )

            wheel_filename, unpack_dir = self._download_prebuilt(
                req=req,
                req_type=req_type,
                resolved_version=fallback_version,
                wheel_url=wheel_url,
            )

            logger.info(
                "test mode: successfully used pre-built wheel for %s==%s",
                req.name,
                fallback_version,
            )
            # Package succeeded via fallback - no failure to record

            return SourceBuildResult(
                wheel_filename=wheel_filename,
                sdist_filename=None,
                unpack_dir=unpack_dir,
                sdist_root_dir=None,
                build_env=None,
                source_type=SourceType.PREBUILT,
            )

        except Exception as fallback_error:
            logger.error(
                "test mode: pre-built fallback also failed for %s: %s",
                req.name,
                fallback_error,
                exc_info=True,
            )
            # Return None to signal failure; bootstrap() will record via re-raised exception
            return None

    # -------------------------------------------------------------------------
    # Resolution delegation methods
    # These methods delegate to ResolutionManager but are kept for backward
    # compatibility with existing code and tests.
    # -------------------------------------------------------------------------

    def _resolve_source_with_history(
        self,
        req: Requirement,
        req_type: RequirementType,
    ) -> tuple[str, Version]:
        """Resolve source for a package, checking history first.

        Delegation method for backward compatibility.
        The actual implementation is in ResolutionManager.
        """
        return self.resolver._resolve_source_with_history(req, req_type, why=self.why)

    def _resolve_version_from_git_url(self, req: Requirement) -> tuple[str, Version]:
        """Resolve version by cloning a git repository.

        Delegation method for backward compatibility with tests.
        The actual implementation is in ResolutionManager.
        """
        return self.resolver._resolve_version_from_git_url(req)

    def _get_version_from_package_metadata(
        self,
        req: Requirement,
        source_dir: pathlib.Path,
    ) -> Version:
        """Extract version from package metadata after cloning.

        Delegation method for backward compatibility with tests.
        The actual implementation is in ResolutionManager.
        """
        return self.resolver._get_version_from_package_metadata(req, source_dir)

    def _resolve_prebuilt_with_history(
        self,
        req: Requirement,
        req_type: RequirementType,
    ) -> tuple[str, Version]:
        """Resolve a pre-built wheel, checking history first.

        Delegation method for backward compatibility.
        The actual implementation is in ResolutionManager.
        """
        return self.resolver._resolve_prebuilt_with_history(req, req_type, why=self.why)

    def _resolve_from_graph(
        self,
        req: Requirement,
        req_type: RequirementType,
        pre_built: bool,
    ) -> tuple[str, Version] | None:
        """Try to resolve from dependency graph history.

        Delegation method for backward compatibility with tests.
        The actual implementation is in ResolutionManager.
        """
        return self.resolver._resolve_from_graph(req, req_type, pre_built, why=self.why)

    def _create_unpack_dir(
        self, req: Requirement, resolved_version: Version
    ) -> pathlib.Path:
        """Create a directory for unpacking wheel metadata.

        Delegation method for backward compatibility.
        The actual implementation is in ResolutionManager.
        """
        return self.resolver.create_unpack_dir(req, resolved_version)

    def _add_to_graph(
        self,
        req: Requirement,
        req_type: RequirementType,
        req_version: Version,
        download_url: str,
        parent: tuple[Requirement, Version] | None,
    ) -> None:
        if req_type == RequirementType.TOP_LEVEL:
            return

        parent_req, parent_version = parent if parent else (None, None)
        pbi = self.ctx.package_build_info(req)
        # Update the dependency graph after we determine that this requirement is
        # useful but before we determine if it is redundant so that we capture all
        # edges to use for building a valid constraints file.
        self.ctx.dependency_graph.add_dependency(
            parent_name=canonicalize_name(parent_req.name) if parent_req else None,
            parent_version=parent_version,
            req_type=req_type,
            req=req,
            req_version=req_version,
            download_url=download_url,
            pre_built=pbi.pre_built,
            constraint=self.ctx.constraints.get_constraint(req.name),
        )
        self.ctx.write_to_graph_to_file()

    def _sort_requirements(
        self,
        requirements: typing.Iterable[Requirement],
    ) -> typing.Iterable[Requirement]:
        return sorted(requirements, key=operator.attrgetter("name"))

    def _resolved_key(
        self, req: Requirement, version: Version, typ: typing.Literal["sdist", "wheel"]
    ) -> SeenKey:
        return (
            canonicalize_name(req.name),
            tuple(sorted(req.extras)),
            str(version),
            typ,
        )

    def _mark_as_seen(
        self,
        req: Requirement,
        version: Version,
        sdist_only: bool = False,
    ) -> None:
        """Track sdist and wheel builds

        A sdist-only build just contains as an sdist.
        A wheel build counts as wheel and sdist, because the presence of a
        either implies we have built a wheel from an sdist or we have a
        prebuilt wheel that will never have an sdist.
        """
        # Mark sdist seen for sdist-only build and wheel build
        self._seen_requirements.add(self._resolved_key(req, version, "sdist"))
        if not sdist_only:
            # Mark wheel seen only for wheel build
            self._seen_requirements.add(self._resolved_key(req, version, "wheel"))

    def _has_been_seen(
        self,
        req: Requirement,
        version: Version,
        sdist_only: bool = False,
    ) -> bool:
        typ: typing.Literal["sdist", "wheel"] = "sdist" if sdist_only else "wheel"
        return self._resolved_key(req, version, typ) in self._seen_requirements

    def _add_to_build_order(
        self,
        req: Requirement,
        version: Version,
        source_url: str,
        source_type: SourceType,
        prebuilt: bool = False,
        constraint: Requirement | None = None,
    ) -> None:
        # We only care if this version of this package has been built,
        # and don't want to trigger building it twice. The "extras"
        # value, included in the _resolved_key() output, can confuse
        # that so we ignore itand build our own key using just the
        # name and version.
        key = (canonicalize_name(req.name), str(version))
        if key in self._build_requirements:
            return
        logger.info(f"adding {key} to build order")
        self._build_requirements.add(key)
        info = {
            "req": str(req),
            "constraint": str(constraint) if constraint else "",
            "dist": canonicalize_name(req.name),
            "version": str(version),
            "prebuilt": prebuilt,
            "source_url": source_url,
            "source_url_type": str(source_type),
        }
        if req.url:
            info["source_url"] = req.url
        self._build_stack.append(info)
        with open(self._build_order_filename, "w") as f:
            # Set default=str because the why value includes
            # Requirement and Version instances that can't be
            # converted to JSON without help.
            json.dump(self._build_stack, f, indent=2, default=str)

    def finalize(self) -> int:
        """Finalize bootstrap and return exit code.

        In test mode, writes failure report and returns non-zero if there were failures.

        Returns:
            0 if all packages built successfully (or not in test mode)
            1 if any packages failed in test mode
        """
        if not self.test_mode:
            return 0

        if not self.failed_packages:
            logger.info("test mode: all packages processed successfully")
            return 0

        # Write JSON failure report with timestamp for uniqueness
        timestamp = datetime.datetime.now(tz=datetime.UTC).strftime("%Y%m%d-%H%M%S-%f")
        failures_file = self.ctx.work_dir / f"test-mode-failures-{timestamp}.json"
        with open(failures_file, "w") as f:
            json.dump({"failures": self.failed_packages}, f, indent=2)
        logger.info("test mode: wrote failure report to %s", failures_file)

        # Log summary
        failed_names = [f["package"] for f in self.failed_packages]
        logger.error(
            "test mode: %d package(s) failed: %s",
            len(self.failed_packages),
            ", ".join(failed_names),
        )
        return 1
