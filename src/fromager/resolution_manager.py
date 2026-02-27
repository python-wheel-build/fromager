"""Resolution management for the bootstrap process.

This module provides the ResolutionManager class which handles all resolution
logic for requirements, including:
- Version resolution from various sources (PyPI, cache, git URLs)
- Cached wheel lookup (local filesystem and remote cache servers)
- History-based resolution from previous bootstrap runs

The ResolutionManager is designed to be used by the Bootstrapper class,
which handles the overall bootstrap orchestration (build order, dependency
tracking, builds).

This separation follows the Single Responsibility Principle:
- ResolutionManager: "What version should I use for this requirement?"
- Bootstrapper: "How do I build this requirement and its dependencies?"
"""

from __future__ import annotations

import logging
import os
import pathlib
import shutil
import tempfile
import typing
import zipfile
from email.parser import BytesParser
from urllib.parse import urlparse

from packaging.requirements import Requirement
from packaging.version import Version

from . import (
    build_environment,
    dependencies,
    finders,
    resolver,
    server,
    sources,
    wheels,
)
from .dependency_graph import DependencyGraph
from .requirements_file import RequirementType

if typing.TYPE_CHECKING:
    from . import context

logger = logging.getLogger(__name__)

# Type alias for the dependency chain stack used to track why we're processing
# a particular requirement. Each entry is (req_type, requirement, version).
WhyStack = list[tuple[RequirementType, Requirement, Version]]

# Callback type for preparing build dependencies. This is used when resolving
# versions from git URLs where we need to prepare build deps to get metadata.
# The callback takes (req, source_dir, build_env) and returns set[Requirement].
PrepareBuildDepsCallback = typing.Callable[
    [Requirement, pathlib.Path, build_environment.BuildEnvironment],
    set[Requirement],
]


class ResolutionManager:
    """Manages resolution of requirements to specific versions and download URLs.

    This class encapsulates all the logic for determining which version of a
    requirement to use and where to download it from. It supports multiple
    resolution strategies:

    1. Cache lookup - Check if we've already resolved this requirement
    2. History-based resolution - Use versions from a previous bootstrap run
    3. PyPI resolution - Query PyPI for available versions
    4. Git URL resolution - Clone and inspect git repositories
    5. Cached wheel lookup - Find pre-built wheels in local or remote caches

    The manager maintains a cache of resolved requirements to avoid redundant
    resolution work during a single bootstrap run.

    Attributes:
        ctx: The work context providing settings, constraints, and paths.
        prev_graph: Optional dependency graph from a previous bootstrap run.
        cache_wheel_server_url: URL to check for pre-built wheels.
        prepare_build_deps_callback: Optional callback for preparing build
            dependencies when resolving git URLs.
    """

    def __init__(
        self,
        ctx: context.WorkContext,
        prev_graph: DependencyGraph | None = None,
        cache_wheel_server_url: str | None = None,
        prepare_build_deps_callback: PrepareBuildDepsCallback | None = None,
    ) -> None:
        """Initialize the resolution manager.

        Args:
            ctx: The work context for this bootstrap run.
            prev_graph: Optional dependency graph from a previous run for
                history-based resolution.
            cache_wheel_server_url: URL of a wheel server to check for
                pre-built wheels.
            prepare_build_deps_callback: Optional callback to prepare build
                dependencies. Required for git URL resolution that needs to
                extract version from package metadata.
        """
        self.ctx = ctx
        self.prev_graph = prev_graph
        self.cache_wheel_server_url = cache_wheel_server_url or ctx.wheel_server_url

        # Callback for preparing build dependencies, used by
        # _get_version_from_package_metadata when resolving git URLs
        self._prepare_build_deps_callback = prepare_build_deps_callback

        # Cache of already-resolved requirements to avoid redundant resolution.
        # Key: string representation of requirement
        # Value: (source_url, version) tuple
        self._resolved_requirements: dict[str, tuple[str, Version]] = {}

    def resolve_version(
        self,
        req: Requirement,
        req_type: RequirementType,
        why: WhyStack | None = None,
    ) -> tuple[str, Version]:
        """Resolve the version of a requirement.

        This is the main entry point for version resolution. It checks the
        cache first, then delegates to either pre-built or source resolution
        depending on the package configuration.

        Args:
            req: The requirement to resolve.
            req_type: The type of requirement (top-level, install, build, etc.)
            why: Optional dependency chain stack for context in graph resolution.
                Defaults to empty list if not provided.

        Returns:
            Tuple of (source_url, version) where source_url is the download URL
            for the source or wheel.
        """
        if why is None:
            why = []

        req_str = str(req)
        if req_str in self._resolved_requirements:
            logger.debug(f"resolved {req_str} from cache")
            return self._resolved_requirements[req_str]

        pbi = self.ctx.package_build_info(req)
        if pbi.pre_built:
            source_url, resolved_version = self._resolve_prebuilt_with_history(
                req=req,
                req_type=req_type,
                why=why,
            )
        else:
            source_url, resolved_version = self._resolve_source_with_history(
                req=req,
                req_type=req_type,
                why=why,
            )

        self._resolved_requirements[req_str] = (source_url, resolved_version)
        return source_url, resolved_version

    # -------------------------------------------------------------------------
    # Cached wheel lookup methods
    # -------------------------------------------------------------------------

    def find_cached_wheel(
        self,
        req: Requirement,
        resolved_version: Version,
    ) -> tuple[pathlib.Path | None, pathlib.Path | None]:
        """Look for cached wheel in multiple locations.

        Checks for cached wheels in order of preference:
        1. wheels_build directory (previously built wheels)
        2. wheels_downloads directory (previously downloaded wheels)
        3. Cache server (remote cache, if configured)

        Args:
            req: The requirement to find a wheel for.
            resolved_version: The specific version to look for.

        Returns:
            Tuple of (cached_wheel_filename, unpacked_cached_wheel_dir).
            Both are None if no cached wheel was found.
        """
        # Check if we have previously built a wheel and still have it on the
        # local filesystem.
        cached_wheel, unpacked = self._look_for_existing_wheel(
            req, resolved_version, self.ctx.wheels_build
        )
        if cached_wheel:
            return cached_wheel, unpacked

        # Check if we have previously downloaded a wheel and still have it
        # on the local filesystem.
        cached_wheel, unpacked = self._look_for_existing_wheel(
            req, resolved_version, self.ctx.wheels_downloads
        )
        if cached_wheel:
            return cached_wheel, unpacked

        # Look for a wheel on the cache server and download it if there is one.
        cached_wheel, unpacked = self._download_wheel_from_cache(req, resolved_version)
        if cached_wheel:
            return cached_wheel, unpacked

        return None, None

    def _look_for_existing_wheel(
        self,
        req: Requirement,
        resolved_version: Version,
        search_in: pathlib.Path,
    ) -> tuple[pathlib.Path | None, pathlib.Path | None]:
        """Look for an existing wheel in a specific directory.

        Args:
            req: The requirement to find a wheel for.
            resolved_version: The specific version to look for.
            search_in: The directory to search in.

        Returns:
            Tuple of (wheel_filename, metadata_dir). Both None if not found
            or if the wheel's build tag doesn't match expectations.
        """
        pbi = self.ctx.package_build_info(req)
        expected_build_tag = pbi.build_tag(resolved_version)
        logger.info(
            f"looking for existing wheel for version {resolved_version} "
            f"with build tag {expected_build_tag} in {search_in}"
        )
        wheel_filename = finders.find_wheel(
            downloads_dir=search_in,
            req=req,
            dist_version=str(resolved_version),
            build_tag=expected_build_tag,
        )
        if not wheel_filename:
            return None, None

        _, _, build_tag, _ = wheels.extract_info_from_wheel_file(req, wheel_filename)
        if expected_build_tag and expected_build_tag != build_tag:
            logger.info(
                f"found wheel for {resolved_version} in {wheel_filename} but "
                f"build tag does not match. Got {build_tag} but expected "
                f"{expected_build_tag}"
            )
            return None, None

        logger.info(f"found existing wheel {wheel_filename}")
        metadata_dir = self._unpack_metadata_from_wheel(
            req, resolved_version, wheel_filename
        )
        return wheel_filename, metadata_dir

    def _download_wheel_from_cache(
        self, req: Requirement, resolved_version: Version
    ) -> tuple[pathlib.Path | None, pathlib.Path | None]:
        """Try to download a wheel from the cache server.

        Args:
            req: The requirement to find a wheel for.
            resolved_version: The specific version to look for.

        Returns:
            Tuple of (wheel_filename, unpack_dir). Both None if not found
            or if download fails.
        """
        if not self.cache_wheel_server_url:
            return None, None
        logger.info(
            f"checking if wheel was already uploaded to {self.cache_wheel_server_url}"
        )
        try:
            wheel_url, _ = resolver.resolve(
                ctx=self.ctx,
                req=Requirement(f"{req.name}=={resolved_version}"),
                sdist_server_url=self.cache_wheel_server_url,
                include_sdists=False,
                include_wheels=True,
            )
            wheelfile_name = pathlib.Path(urlparse(wheel_url).path)
            pbi = self.ctx.package_build_info(req)
            expected_build_tag = pbi.build_tag(resolved_version)
            # Log the expected build tag for debugging
            logger.info(f"has expected build tag {expected_build_tag}")
            # Get changelogs for debug info
            changelogs = pbi.get_changelog(resolved_version)
            logger.debug(f"has change logs {changelogs}")

            _, _, build_tag, _ = wheels.extract_info_from_wheel_file(
                req, wheelfile_name
            )
            if expected_build_tag and expected_build_tag != build_tag:
                logger.info(
                    f"found wheel for {resolved_version} in cache but build tag "
                    f"does not match. Got {build_tag} but expected {expected_build_tag}"
                )
                return None, None

            cached_wheel = wheels.download_wheel(
                req=req, wheel_url=wheel_url, output_directory=self.ctx.wheels_downloads
            )
            if self.cache_wheel_server_url != self.ctx.wheel_server_url:
                # Only update the local server if we actually downloaded
                # something from a different server.
                server.update_wheel_mirror(self.ctx)
            logger.info("found built wheel on cache server")
            unpack_dir = self._unpack_metadata_from_wheel(
                req, resolved_version, cached_wheel
            )
            return cached_wheel, unpack_dir
        except Exception:
            logger.info(
                f"did not find wheel for {resolved_version} in "
                f"{self.cache_wheel_server_url}"
            )
            return None, None

    def _unpack_metadata_from_wheel(
        self, req: Requirement, resolved_version: Version, wheel_filename: pathlib.Path
    ) -> pathlib.Path | None:
        """Extract build requirement metadata from a wheel file.

        This extracts the fromager-specific build requirement files from the
        wheel's metadata directory.

        Args:
            req: The requirement the wheel belongs to.
            resolved_version: The version of the wheel.
            wheel_filename: Path to the wheel file.

        Returns:
            Path to the directory containing extracted metadata, or None if
            extraction failed (e.g., non-fromager wheel).
        """
        dist_name, dist_version, _, _ = wheels.extract_info_from_wheel_file(
            req,
            wheel_filename,
        )
        unpack_dir = self.create_unpack_dir(req, resolved_version)
        dist_filename = f"{dist_name}-{dist_version}"
        metadata_dir = pathlib.Path(f"{dist_filename}.dist-info")
        req_filenames: list[str] = [
            dependencies.BUILD_BACKEND_REQ_FILE_NAME,
            dependencies.BUILD_SDIST_REQ_FILE_NAME,
            dependencies.BUILD_SYSTEM_REQ_FILE_NAME,
        ]
        try:
            archive = zipfile.ZipFile(wheel_filename)
            for filename in req_filenames:
                zipinfo = archive.getinfo(
                    str(metadata_dir / f"{wheels.FROMAGER_BUILD_REQ_PREFIX}-{filename}")
                )
                # Check for path traversal attempts
                if os.path.isabs(zipinfo.filename) or ".." in zipinfo.filename:
                    raise ValueError(f"Unsafe path in wheel: {zipinfo.filename}")
                zipinfo.filename = filename
                output_file = archive.extract(zipinfo, unpack_dir)
                logger.info(f"extracted {output_file}")

            logger.info(f"extracted build requirements from wheel into {unpack_dir}")
            return unpack_dir
        except Exception as e:
            # implies that the wheel server hosted non-fromager built wheels
            logger.info(f"could not extract build requirements from wheel: {e}")
            for filename in req_filenames:
                unpack_dir.joinpath(filename).unlink(missing_ok=True)
            return None

    def create_unpack_dir(
        self, req: Requirement, resolved_version: Version
    ) -> pathlib.Path:
        """Create a directory for unpacking wheel metadata.

        Args:
            req: The requirement to create the directory for.
            resolved_version: The version being processed.

        Returns:
            Path to the created directory.
        """
        unpack_dir = self.ctx.work_dir / f"{req.name}-{resolved_version}"
        unpack_dir.mkdir(parents=True, exist_ok=True)
        return unpack_dir

    # -------------------------------------------------------------------------
    # Version resolution methods
    # -------------------------------------------------------------------------

    def _resolve_prebuilt_with_history(
        self,
        req: Requirement,
        req_type: RequirementType,
        why: WhyStack,
    ) -> tuple[str, Version]:
        """Resolve a pre-built wheel, checking history first.

        Args:
            req: The requirement to resolve.
            req_type: The type of requirement.
            why: The dependency chain stack for context.

        Returns:
            Tuple of (wheel_url, version).
        """
        cached_resolution = self._resolve_from_graph(
            req=req,
            req_type=req_type,
            pre_built=True,
            why=why,
        )

        if cached_resolution and not req.url:
            wheel_url, resolved_version = cached_resolution
            logger.debug(f"resolved from previous bootstrap to {resolved_version}")
        else:
            servers = wheels.get_wheel_server_urls(
                self.ctx, req, cache_wheel_server_url=resolver.PYPI_SERVER_URL
            )
            wheel_url, resolved_version = wheels.resolve_prebuilt_wheel(
                ctx=self.ctx, req=req, wheel_server_urls=servers, req_type=req_type
            )
        return (wheel_url, resolved_version)

    def _resolve_source_with_history(
        self,
        req: Requirement,
        req_type: RequirementType,
        why: WhyStack,
    ) -> tuple[str, Version]:
        """Resolve source for a package, checking history first.

        Args:
            req: The requirement to resolve.
            req_type: The type of requirement.
            why: The dependency chain stack for context.

        Returns:
            Tuple of (source_url, version).

        Raises:
            ValueError: If req has a URL but is not a top-level dependency.
        """
        if req.url:
            # If we have a URL, we should use that source. For now we only
            # support git clone URLs of some sort. We are given the directory
            # where the cloned repo resides, and return that as the URL for the
            # source code so the next step in the process can find it and
            # operate on it. However, we only support that if the package is a
            # top-level dependency.
            if req_type != RequirementType.TOP_LEVEL:
                raise ValueError(
                    f"{req} includes a URL, but is not a top-level dependency"
                )
            logger.info("resolving source via URL, ignoring any plugins")
            return self._resolve_version_from_git_url(req=req)

        cached_resolution = self._resolve_from_graph(
            req=req,
            req_type=req_type,
            pre_built=False,
            why=why,
        )
        if cached_resolution:
            source_url, resolved_version = cached_resolution
            logger.debug(f"resolved from previous bootstrap to {resolved_version}")
        else:
            source_url, resolved_version = sources.resolve_source(
                ctx=self.ctx,
                req=req,
                sdist_server_url=resolver.PYPI_SERVER_URL,
                req_type=req_type,
            )
        return (source_url, resolved_version)

    def _resolve_version_from_git_url(self, req: Requirement) -> tuple[str, Version]:
        """Resolve version by cloning a git repository.

        This handles requirements specified with git URLs. It clones the
        repository to determine the version from the package metadata.

        Args:
            req: The requirement with a git URL.

        Returns:
            Tuple of (path_to_cloned_repo, version).

        Raises:
            ValueError: If the URL is missing or not a git URL.
        """
        if not req.url:
            raise ValueError(f"unable to resolve from URL with no URL in {req}")

        if not req.url.startswith("git+"):
            raise ValueError(f"unable to handle URL scheme in {req.url} from {req}")

        # We start by not knowing where we would put the source because we don't
        # know the version.
        working_src_dir: pathlib.Path | None = None
        version: Version | None = None

        # Clean up the URL so we can parse it
        reduced_url = req.url[len("git+") :]
        parsed_url = urlparse(reduced_url)

        # Save the URL that we think we will use for cloning. This might change
        # later if the path has a tag or branch in it.
        url_to_clone = reduced_url
        need_to_clone = False

        # If the URL includes an @ with text after it, we use that as the
        # reference to clone, but by default we take the default branch.
        git_ref: str | None = None

        if "@" not in parsed_url.path:
            # If we have no reference, we know we are going to have to clone the
            # repository to figure out the version to use.
            logger.debug("no reference in URL, will clone")
            need_to_clone = True
        else:
            # If we have a reference, it might be a valid python version string,
            # or not. It _must_ be a valid git reference. If it can be parsed as
            # a valid python version, we assume the tag points to source that
            # will think that is its version, so we allow reusing an existing
            # cloned repo if there is one.
            new_path, _, git_ref = parsed_url.path.rpartition("@")
            url_to_clone = parsed_url._replace(path=new_path).geturl()
            try:
                version = Version(git_ref)
            except ValueError:
                logger.info(
                    "could not parse %r as a version, cloning to get the version",
                    git_ref,
                )
                need_to_clone = True
            else:
                logger.info("URL %s includes version %s", req.url, version)
                working_src_dir = (
                    self.ctx.work_dir
                    / f"{req.name}-{version}"
                    / f"{req.name}-{version}"
                )
                if not working_src_dir.exists():
                    need_to_clone = True
                else:
                    if self.ctx.cleanup:
                        logger.debug("cleaning up %s to reclone", working_src_dir)
                        shutil.rmtree(working_src_dir)
                        need_to_clone = True
                    else:
                        logger.info("reusing %s", working_src_dir)

        if need_to_clone:
            with tempfile.TemporaryDirectory() as tmpdir:
                clone_dir = pathlib.Path(tmpdir) / "src"
                sources.download_git_source(
                    ctx=self.ctx,
                    req=req,
                    url_to_clone=url_to_clone,
                    destination_dir=clone_dir,
                    ref=git_ref,
                )
                if not version:
                    # If we still do not have a version, get it from the package
                    # metadata.
                    version = self._get_version_from_package_metadata(req, clone_dir)
                    logger.info("found version %s", version)
                    working_src_dir = (
                        self.ctx.work_dir
                        / f"{req.name}-{version}"
                        / f"{req.name}-{version}"
                    )
                    if working_src_dir.exists():
                        # We have to check if the destination directory exists
                        # because if we were not given a version we did not
                        # clean it up earlier. We do not use ctx.cleanup to
                        # control this action because we cannot trust that the
                        # destination directory is reusable because we have had
                        # to compute the version and we cannot be sure that the
                        # version is dynamic. Two different commits in the repo
                        # could have the same version if that version is set
                        # with static data in the repo instead of via a tag or
                        # dynamically computed by something like setuptools-scm.
                        logger.debug("cleaning up %s", working_src_dir)
                        shutil.rmtree(working_src_dir)
                        working_src_dir.parent.mkdir(parents=True, exist_ok=True)
                logger.info("moving cloned repo to %s", working_src_dir)
                shutil.move(clone_dir, str(working_src_dir))

        if not version:
            raise ValueError(f"unable to determine version for {req}")

        if not working_src_dir:
            raise ValueError(f"unable to determine working source directory for {req}")

        logging.info("resolved from git URL to %s, %s", working_src_dir, version)
        return (str(working_src_dir), version)

    def _get_version_from_package_metadata(
        self,
        req: Requirement,
        source_dir: pathlib.Path,
    ) -> Version:
        """Extract version from package metadata after cloning.

        This creates a temporary build environment, prepares build dependencies,
        and uses the PEP 517 metadata hook to get the version.

        Args:
            req: The requirement being processed.
            source_dir: Path to the cloned source directory.

        Returns:
            The extracted version.

        Raises:
            RuntimeError: If prepare_build_deps_callback is not set.
        """
        if self._prepare_build_deps_callback is None:
            raise RuntimeError(
                "Cannot get version from package metadata without "
                "prepare_build_deps_callback being set"
            )

        pbi = self.ctx.package_build_info(req)
        build_dir = pbi.build_dir(source_dir)

        logger.info(
            "preparing build dependencies so we can access the metadata to get "
            "the version"
        )
        build_env = build_environment.BuildEnvironment(
            ctx=self.ctx,
            parent_dir=source_dir.parent,
        )
        # Use the callback to prepare build dependencies
        build_dependencies = self._prepare_build_deps_callback(
            req, source_dir, build_env
        )
        build_env.install(build_dependencies)

        logger.info("generating metadata to get version")
        hook_caller = dependencies.get_build_backend_hook_caller(
            ctx=self.ctx,
            req=req,
            build_dir=build_dir,
            override_environ={},
            build_env=build_env,
        )
        metadata_dir_base = hook_caller.prepare_metadata_for_build_wheel(
            metadata_directory=str(source_dir.parent),
            config_settings=pbi.config_settings,
        )
        metadata_filename = source_dir.parent / metadata_dir_base / "METADATA"
        with open(metadata_filename, "rb") as f:
            p = BytesParser()
            metadata = p.parse(f, headersonly=True)
        return Version(metadata["Version"])

    # -------------------------------------------------------------------------
    # Graph-based resolution methods
    # -------------------------------------------------------------------------

    def _resolve_from_graph(
        self,
        req: Requirement,
        req_type: RequirementType,
        pre_built: bool,
        why: WhyStack,
    ) -> tuple[str, Version] | None:
        """Try to resolve from dependency graph history.

        This method first checks if there's a matching top-level requirement
        in the current graph, then falls back to checking the previous
        bootstrap's graph if available.

        Args:
            req: The requirement to resolve.
            req_type: The type of requirement.
            pre_built: Whether to look for pre-built wheels.
            why: The dependency chain stack to determine the parent.

        Returns:
            Tuple of (url, version) if found in graph, None otherwise.
        """
        _, parent_req, _ = why[-1] if why else (None, None, None)

        if not self.prev_graph:
            return None

        seen_version: set[str] = set()

        # First perform resolution using the top level reqs before looking at
        # history
        possible_versions_in_top_level: list[tuple[str, Version]] = []
        for (
            top_level_edge
        ) in self.ctx.dependency_graph.get_root_node().get_outgoing_edges(
            req.name, RequirementType.TOP_LEVEL
        ):
            possible_versions_in_top_level.append(
                (
                    top_level_edge.destination_node.download_url,
                    top_level_edge.destination_node.version,
                )
            )
            seen_version.add(str(top_level_edge.destination_node.version))

        resolver_result = self._resolve_from_version_source(
            possible_versions_in_top_level, req
        )
        if resolver_result:
            return resolver_result

        # Only if there is nothing in top level reqs, resolve using history
        possible_versions_from_graph: list[tuple[str, Version]] = []
        # Check all nodes which have the same parent name irrespective of the
        # parent's version
        for parent_node in self.prev_graph.get_nodes_by_name(
            parent_req.name if parent_req else None
        ):
            # If the edge matches the current req and type then it is a possible
            # candidate. Filtering on type might not be necessary, but we are
            # being safe here. This will for sure ensure that bootstrap takes
            # the same route as it did in the previous one. If we don't filter
            # by type then it might pick up a different version from a different
            # type that should have appeared much later in the resolution
            # process.
            for edge in parent_node.get_outgoing_edges(req.name, req_type):
                if (
                    edge.destination_node.pre_built == pre_built
                    and str(edge.destination_node.version) not in seen_version
                ):
                    possible_versions_from_graph.append(
                        (
                            edge.destination_node.download_url,
                            edge.destination_node.version,
                        )
                    )
                    seen_version.add(str(edge.destination_node.version))

        return self._resolve_from_version_source(possible_versions_from_graph, req)

    def _resolve_from_version_source(
        self,
        version_source: list[tuple[str, Version]],
        req: Requirement,
    ) -> tuple[str, Version] | None:
        """Resolve from a list of candidate versions.

        Args:
            version_source: List of (url, version) tuples to consider.
            req: The requirement to resolve.

        Returns:
            The best matching (url, version) tuple, or None if no match.
        """
        if not version_source:
            return None
        try:
            # No need to pass req type to enable caching since we are already
            # using the graph as our cache. Do not cache candidates.
            provider = resolver.GenericProvider(
                version_source=lambda identifier: version_source,
                constraints=self.ctx.constraints,
                use_resolver_cache=False,
            )
            return resolver.resolve_from_provider(provider, req)
        except Exception as err:
            logger.debug(f"could not resolve {req} from {version_source}: {err}")
            return None
