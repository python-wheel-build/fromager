"""Requirement resolution for bootstrap process.

Handles PyPI and graph-based resolution strategies.
Git URL resolution stays in Bootstrapper (orchestration concern).
"""

from __future__ import annotations

import logging
import typing

from packaging.requirements import Requirement
from packaging.version import Version

from . import resolver, sources, wheels
from .dependency_graph import DependencyGraph
from .requirements_file import RequirementType

if typing.TYPE_CHECKING:
    from . import context

logger = logging.getLogger(__name__)


class RequirementResolver:
    """Resolve package requirements from PyPI or dependency graph.

    Single Responsibility: Coordinate resolution strategies.
    Reason to Change: Resolution algorithm or provider priorities change.

    Resolution strategies (in order):
    1. Previous dependency graph (if available)
    2. PyPI lookup (via existing sources/resolver modules)

    Git URL resolution is NOT handled here - that stays in Bootstrapper
    because it requires BuildEnvironment and build dependencies.
    """

    def __init__(
        self,
        ctx: context.WorkContext,
        prev_graph: DependencyGraph | None = None,
    ) -> None:
        """Initialize requirement resolver.

        Args:
            ctx: Work context with constraints and settings
            prev_graph: Optional previous dependency graph for caching
        """
        self.ctx = ctx
        self.prev_graph = prev_graph
        # Session-level resolution cache to avoid re-resolving same requirements
        # Key: (requirement_string, pre_built) to distinguish source vs prebuilt
        # Value: list of (url, version) tuples sorted by version (highest first)
        self._resolved_requirements: dict[
            tuple[str, bool], list[tuple[str, Version]]
        ] = {}

    def resolve_all(
        self,
        req: Requirement,
        req_type: RequirementType,
        parent_req: Requirement | None = None,
        pre_built: bool | None = None,
    ) -> list[tuple[str, Version]]:
        """Resolve package requirement to all matching versions.

        Tries resolution strategies in order:
        1. Session cache (if previously resolved)
        2. Previous dependency graph
        3. PyPI resolution (source or prebuilt based on package build info)

        Args:
            req: Package requirement
            req_type: Type of requirement
            parent_req: Parent requirement from dependency chain
            pre_built: Optional override to force prebuilt (True) or source (False).
                If None (default), uses package build info to determine.

        Returns:
            List of (url, version) tuples sorted by version (highest first)

        Raises:
            ValueError: If req contains a git URL and pre_built is False
                (git URL source resolution must be handled by Bootstrapper)
        """
        # Determine pre_built if not specified (needed for cache key and URL guard)
        if pre_built is None:
            pbi = self.ctx.package_build_info(req)
            pre_built = pbi.pre_built

        # Git URL source resolution must be handled by Bootstrapper.
        # But git URL prebuilt resolution is allowed - we look for wheels on PyPI
        # (test mode fallback uses this path).
        if req.url and not pre_built:
            raise ValueError(
                f"Git URL requirements must be handled by Bootstrapper: {req}"
            )

        # Check session cache (keyed by requirement + pre_built)
        cached_result = self.get_cached_resolution(req, pre_built)
        if cached_result is not None:
            logger.debug(f"resolved {req} from cache")
            return cached_result

        # Resolve using strategies
        results = self._resolve(req, req_type, parent_req, pre_built)

        # Cache the result
        self.cache_resolution(req, pre_built, results)
        return results

    def resolve(
        self,
        req: Requirement,
        req_type: RequirementType,
        parent_req: Requirement | None = None,
        pre_built: bool | None = None,
    ) -> tuple[str, Version]:
        """Resolve package requirement to the best matching version.

        Tries resolution strategies in order:
        1. Session cache (if previously resolved)
        2. Previous dependency graph
        3. PyPI resolution (source or prebuilt based on package build info)

        Args:
            req: Package requirement
            req_type: Type of requirement
            parent_req: Parent requirement from dependency chain
            pre_built: Optional override to force prebuilt (True) or source (False).
                If None (default), uses package build info to determine.

        Returns:
            (url, version) tuple for the highest matching version

        Raises:
            ValueError: If req contains a git URL and pre_built is False
                (git URL source resolution must be handled by Bootstrapper)
        """
        results = self.resolve_all(req, req_type, parent_req, pre_built)
        return results[0]

    def _resolve(
        self,
        req: Requirement,
        req_type: RequirementType,
        parent_req: Requirement | None,
        pre_built: bool,
    ) -> list[tuple[str, Version]]:
        """Internal resolution logic without caching.

        Tries resolution strategies in order:
        1. Previous dependency graph
        2. PyPI resolution (source or prebuilt)

        Args:
            req: Package requirement
            req_type: Type of requirement
            parent_req: Parent requirement from dependency chain
            pre_built: Whether to resolve prebuilt (True) or source (False)

        Returns:
            List of (url, version) tuples sorted by version (highest first)
        """
        # Try graph
        cached_resolution = self._resolve_from_graph(
            req=req,
            req_type=req_type,
            pre_built=pre_built,
            parent_req=parent_req,
        )

        if cached_resolution and not req.url:
            logger.debug(
                f"resolved from previous bootstrap: {len(cached_resolution)} version(s)"
            )
            return cached_resolution

        # Fallback to PyPI
        result: list[tuple[str, Version]]
        if pre_built:
            # Resolve prebuilt wheel
            servers = wheels.get_wheel_server_urls(
                self.ctx, req, cache_wheel_server_url=resolver.PYPI_SERVER_URL
            )
            result = wheels.resolve_prebuilt_wheel_all(
                ctx=self.ctx, req=req, wheel_server_urls=servers, req_type=req_type
            )
        else:
            # Resolve source (sdist)
            result = sources.resolve_source_all(
                ctx=self.ctx,
                req=req,
                sdist_server_url=resolver.PYPI_SERVER_URL,
                req_type=req_type,
            )
        return result

    def get_cached_resolution(
        self,
        req: Requirement,
        pre_built: bool,
    ) -> list[tuple[str, Version]] | None:
        """Get a cached resolution result if it exists.

        Args:
            req: Package requirement to look up in cache
            pre_built: Whether looking for prebuilt or source resolution

        Returns:
            List of (url, version) tuples if cached, None otherwise
        """
        cache_key = (str(req), pre_built)
        return self._resolved_requirements.get(cache_key)

    def cache_resolution(
        self,
        req: Requirement,
        pre_built: bool,
        result: list[tuple[str, Version]],
    ) -> None:
        """Cache a resolution result.

        Used by Bootstrapper to cache git URL resolutions that are
        handled externally (outside this resolver).

        Args:
            req: Package requirement to cache
            pre_built: Whether this is a prebuilt or source resolution
            result: List of (url, version) tuples
        """
        cache_key = (str(req), pre_built)
        self._resolved_requirements[cache_key] = result

    def _resolve_from_graph(
        self,
        req: Requirement,
        req_type: RequirementType,
        pre_built: bool,
        parent_req: Requirement | None,
    ) -> list[tuple[str, Version]] | None:
        """Resolve from previous dependency graph.

        Extracted from Bootstrapper._resolve_from_graph().

        Args:
            req: Package requirement
            req_type: Type of requirement
            pre_built: Whether to look for pre-built packages
            parent_req: Parent requirement for graph traversal

        Returns:
            List of (url, version) tuples if found in graph, None otherwise
        """
        if not self.prev_graph:
            return None

        seen_version: set[str] = set()

        # First perform resolution using the top level reqs before looking at history
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
        # Check all nodes which have the same parent name irrespective of the parent's version
        for parent_node in self.prev_graph.get_nodes_by_name(
            parent_req.name if parent_req else None
        ):
            # If the edge matches the current req and type then it is a possible candidate.
            # Filtering on type might not be necessary, but we are being safe here. This will
            # for sure ensure that bootstrap takes the same route as it did in the previous one.
            # If we don't filter by type then it might pick up a different version from a different
            # type that should have appeared much later in the resolution process.
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

        resolver_result = self._resolve_from_version_source(
            possible_versions_from_graph, req
        )
        if resolver_result:
            return resolver_result

        # Fallback: search by package name across the entire previous graph,
        # ignoring parent and req_type.  This handles cases where a dependency
        # is encountered via a new parent or a different req_type that did not
        # exist in the previous graph (#958).
        # NOTE: This fallback ignores both parent and req_type filters.
        # It may pick a version from a different parent or dependency type
        # than the original bootstrap order, but this is preferable to
        # falling through to PyPI and pulling an unpinned version.
        possible_versions_by_name: list[tuple[str, Version]] = []
        for node in self.prev_graph.get_nodes_by_name(req.name):
            if node.pre_built == pre_built and str(node.version) not in seen_version:
                possible_versions_by_name.append((node.download_url, node.version))
                seen_version.add(str(node.version))

        if possible_versions_by_name:
            logger.debug(
                "%s: name-based fallback found versions in previous graph: %s",
                req.name,
                [str(v) for _, v in possible_versions_by_name],
            )
        else:
            logger.debug(
                "%s: no versions found in previous graph by name either",
                req.name,
            )

        return self._resolve_from_version_source(possible_versions_by_name, req)

    def _resolve_from_version_source(
        self,
        version_source: list[tuple[str, Version]],
        req: Requirement,
    ) -> list[tuple[str, Version]] | None:
        """Filter and return all matching versions from candidates.

        Extracted from Bootstrapper._resolve_from_version_source().

        Args:
            version_source: List of (url, version) candidates
            req: Package requirement with version specifier

        Returns:
            List of (url, version) tuples for all matches, None if no matches
        """
        if not version_source:
            return None
        try:
            # No need to pass req type to enable caching since we are already using the graph as our cache.
            # Do not cache candidates.
            provider = resolver.GenericProvider(
                version_source=lambda identifier: version_source,
                constraints=self.ctx.constraints,
                use_resolver_cache=False,
            )
            # resolve_from_provider now returns all matching candidates
            return resolver.resolve_from_provider(provider, req)
        except Exception as err:
            logger.debug(f"could not resolve {req} from {version_source}: {err}")
            return None
