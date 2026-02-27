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
        self._resolved_requirements: dict[str, tuple[str, Version]] = {}

    def resolve_source(
        self,
        req: Requirement,
        req_type: RequirementType,
        parent_req: Requirement | None = None,
    ) -> tuple[str, Version]:
        """Resolve source package (sdist).

        Tries resolution strategies in order:
        1. Session cache (if previously resolved)
        2. Previous dependency graph
        3. PyPI source resolution

        Args:
            req: Package requirement (must NOT have URL)
            req_type: Type of requirement
            parent_req: Parent requirement from dependency chain

        Returns:
            Tuple of (source_url, resolved_version)

        Raises:
            ValueError: If req contains a URL (must use Bootstrapper for git URLs)
        """
        if req.url:
            raise ValueError(
                f"Git URL requirements must be handled by Bootstrapper: {req}"
            )

        # Check session cache first
        req_str = str(req)
        if req_str in self._resolved_requirements:
            logger.debug(f"resolved {req_str} from cache")
            return self._resolved_requirements[req_str]

        # Try graph
        cached_resolution = self._resolve_from_graph(
            req=req,
            req_type=req_type,
            pre_built=False,
            parent_req=parent_req,
        )
        if cached_resolution:
            source_url, resolved_version = cached_resolution
            logger.debug(f"resolved from previous bootstrap to {resolved_version}")
        else:
            # Fallback to PyPI
            source_url, resolved_version = sources.resolve_source(
                ctx=self.ctx,
                req=req,
                sdist_server_url=resolver.PYPI_SERVER_URL,
                req_type=req_type,
            )

        # Cache the result
        self._resolved_requirements[req_str] = (source_url, resolved_version)
        return source_url, resolved_version

    def resolve_prebuilt(
        self,
        req: Requirement,
        req_type: RequirementType,
        parent_req: Requirement | None = None,
    ) -> tuple[str, Version]:
        """Resolve pre-built package (wheels only).

        Tries resolution strategies in order:
        1. Session cache (if previously resolved)
        2. Previous dependency graph
        3. PyPI wheel resolution

        Args:
            req: Package requirement
            req_type: Type of requirement
            parent_req: Parent requirement from dependency chain

        Returns:
            Tuple of (source_url, resolved_version)

        Raises:
            ValueError: If unable to resolve
        """
        # Check session cache first
        req_str = str(req)
        if req_str in self._resolved_requirements:
            logger.debug(f"resolved {req_str} from cache")
            return self._resolved_requirements[req_str]

        # Try graph
        cached_resolution = self._resolve_from_graph(
            req=req,
            req_type=req_type,
            pre_built=True,
            parent_req=parent_req,
        )

        if cached_resolution and not req.url:
            wheel_url, resolved_version = cached_resolution
            logger.debug(f"resolved from previous bootstrap to {resolved_version}")
        else:
            # Fallback to PyPI prebuilt resolution
            servers = wheels.get_wheel_server_urls(
                self.ctx, req, cache_wheel_server_url=resolver.PYPI_SERVER_URL
            )
            wheel_url, resolved_version = wheels.resolve_prebuilt_wheel(
                ctx=self.ctx, req=req, wheel_server_urls=servers, req_type=req_type
            )

        # Cache the result
        self._resolved_requirements[req_str] = (wheel_url, resolved_version)
        return wheel_url, resolved_version

    def cache_resolution(
        self,
        req_str: str,
        result: tuple[str, Version],
    ) -> None:
        """Cache a resolution result.

        Used by Bootstrapper to cache git URL resolutions that are
        handled externally (outside this resolver).

        Args:
            req_str: String representation of the requirement
            result: Tuple of (source_url, resolved_version)
        """
        self._resolved_requirements[req_str] = result

    def _resolve_from_graph(
        self,
        req: Requirement,
        req_type: RequirementType,
        pre_built: bool,
        parent_req: Requirement | None,
    ) -> tuple[str, Version] | None:
        """Resolve from previous dependency graph.

        Extracted from Bootstrapper._resolve_from_graph().

        Args:
            req: Package requirement
            req_type: Type of requirement
            pre_built: Whether to look for pre-built packages
            parent_req: Parent requirement for graph traversal

        Returns:
            Tuple of (url, version) if found in graph, None otherwise
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

        return self._resolve_from_version_source(possible_versions_from_graph, req)

    def _resolve_from_version_source(
        self,
        version_source: list[tuple[str, Version]],
        req: Requirement,
    ) -> tuple[str, Version] | None:
        """Select best version from candidates.

        Extracted from Bootstrapper._resolve_from_version_source().

        Args:
            version_source: List of (url, version) candidates
            req: Package requirement with version specifier

        Returns:
            Tuple of (url, version) for best match, None if no match
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
            return resolver.resolve_from_provider(provider, req)
        except Exception as err:
            logger.debug(f"could not resolve {req} from {version_source}: {err}")
            return None
