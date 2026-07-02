"""Requirement resolution for bootstrap process.

Handles PyPI and graph-based resolution strategies.
Git URL resolution stays in Bootstrapper (orchestration concern).
"""

from __future__ import annotations

import logging
import threading
import typing

from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version

from . import finders, resolver, sources, wheels
from .dependency_graph import DependencyGraph
from .requirements_file import RequirementType

if typing.TYPE_CHECKING:
    from . import context

logger = logging.getLogger(__name__)


class BootstrapRequirementResolver:
    """Resolve package requirements from PyPI or dependency graph during bootstrap.

    Single Responsibility: Coordinate resolution strategies for bootstrap process.
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
        multiple_versions: bool = False,
        cache_wheel_server_url: str = "",
    ) -> None:
        """Initialize requirement resolver.

        Args:
            ctx: Work context with constraints and settings
            prev_graph: Optional previous dependency graph for caching
            multiple_versions: If ``True`` and no results are found through
                any other approach, takes the latest candidate from the
                cache server, ignoring the age filters.  In all other
                cases, returns an empty list when no candidates are found.
            cache_wheel_server_url: URL of the remote wheel cache server.
                Used as a fallback when age filtering produces no candidates.
        """
        self.ctx = ctx
        self.prev_graph = prev_graph
        self.multiple_versions = multiple_versions
        self.cache_wheel_server_url = cache_wheel_server_url
        # All known versions for a package, accumulated across resolution
        # contexts.  Versions discovered via different specifiers or req_types
        # are merged so that later lookups see the widest set.
        # Key: (normalized_name, pre_built)
        # Value: {version: url}
        self._known_versions: dict[tuple[NormalizedName, bool], dict[Version, str]] = {}
        # Requirement rules already resolved from network/graph.
        # Key: (str(req), pre_built)
        # Prevents redundant network calls for the same specifier.
        self._resolved_rules: set[tuple[str, bool]] = set()
        # Protects _known_versions and _resolved_rules for thread safety.
        self._lock = threading.Lock()

    def resolve(
        self,
        req: Requirement,
        req_type: RequirementType,
        parent_req: Requirement | None = None,
        pre_built: bool | None = None,
        return_all_versions: bool = False,
    ) -> list[tuple[str, Version]]:
        """Resolve package requirement to matching version(s).

        Uses a two-step strategy:
        1. If this requirement rule has not been resolved before, fetch
           versions from the network (or previous graph) and extend the
           package-level known-versions cache.
        2. Filter all known versions for the package by the current
           requirement specifier.

        This ensures that versions discovered in one context (e.g.,
        top-level with cooldown bypass) are visible to later lookups
        with different specifiers for the same package.

        Args:
            req: Package requirement
            req_type: Type of requirement
            parent_req: Parent requirement from dependency chain
            pre_built: Optional override to force prebuilt (True) or source (False).
                If None (default), uses package build info to determine.
            return_all_versions: If True, return all matching versions. If False,
                return only the highest matching version.

        Returns:
            List of (url, version) tuples sorted by version (highest first).
            Contains one item when return_all_versions=False, or all matching
            versions when return_all_versions=True.

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

        rule_key = (str(req), pre_built)

        with self._lock:
            if rule_key not in self._resolved_rules:
                # Rule not seen before — resolve from graph or network and
                # extend the package-level known-versions cache.
                self._resolve_and_extend(req, req_type, pre_built, parent_req)
                self._resolved_rules.add(rule_key)
            else:
                logger.debug(f"rule already resolved: {req}")

            # Filter all known versions by the current requirement specifier.
            matching = self._get_matching_versions(req, pre_built)

        if not matching:
            return []
        if return_all_versions:
            return matching
        return [matching[0]]

    def _resolve_and_extend(
        self,
        req: Requirement,
        req_type: RequirementType,
        pre_built: bool,
        parent_req: Requirement | None,
    ) -> None:
        """Resolve versions from graph/network and extend known versions cache."""
        # Try previous dependency graph
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
            results = cached_resolution
        elif pre_built:
            # Resolve prebuilt wheel
            wheel_server_urls = wheels.get_wheel_server_urls(
                self.ctx, req, cache_wheel_server_url=resolver.PYPI_SERVER_URL
            )
            results = wheels.resolve_all_prebuilt_wheels(
                ctx=self.ctx,
                req=req,
                wheel_server_urls=wheel_server_urls,
                req_type=req_type,
            )
        else:
            # Resolve source (sdist)
            provider = sources.get_source_provider(
                ctx=self.ctx,
                req=req,
                sdist_server_url=resolver.PYPI_SERVER_URL,
                req_type=req_type,
            )
            max_age_cutoff = resolver._compute_max_age_cutoff(self.ctx)
            results = resolver.find_all_matching_from_provider(
                provider,
                req,
                max_age_cutoff=max_age_cutoff,
                fallback_on_empty_age_filter=not self.multiple_versions,
            )

            if not results and self.multiple_versions and self.cache_wheel_server_url:
                logger.info(
                    "no results found with normal resolution, "
                    "falling back to the cache server %s",
                    self.cache_wheel_server_url,
                )
                results = self._resolve_from_cache_server(req, req_type)

            if not results:
                logger.warning(
                    "resolver returned no results "
                    "(wheel server URL %s, %s version mode)",
                    self.cache_wheel_server_url or "(none)",
                    "multiple" if self.multiple_versions else "single",
                )

        if results:
            self._extend_known_versions(req, pre_built, results)

    def _resolve_from_cache_server(
        self, req: Requirement, req_type: RequirementType
    ) -> list[tuple[str, Version]]:
        """Fall back to the remote wheel cache server for a cached version.

        When age filtering removes all candidates in multi-version mode,
        queries the remote cache server (both wheels and sdists) to find
        the newest available version, then re-resolves the sdist URL
        through the normal source provider (including overrides).

        Returns at most one version so that transitive dependencies are
        re-processed without rebuilding every old version.
        """
        logger.info(
            "checking cache server %s for existing build",
            self.cache_wheel_server_url,
        )
        best: tuple[str, Version] | None = None
        for include_sdists, include_wheels in [(False, True), (True, False)]:
            try:
                provider = finders.PyPICacheProvider(
                    cache_server_url=self.cache_wheel_server_url,
                    constraints=self.ctx.constraints,
                    include_sdists=include_sdists,
                    include_wheels=include_wheels,
                )
                results = resolver.find_all_matching_from_provider(provider, req)
                if results:
                    url, version = results[0]
                    if best is None or version > best[1]:
                        best = (url, version)
            except Exception as err:
                logger.warning(
                    "error checking cache server %s: %s",
                    self.cache_wheel_server_url,
                    err,
                )

        if best is None:
            logger.debug(
                "no versions found on cache server %s for %s",
                self.cache_wheel_server_url,
                req.name,
            )
            return []

        _, version = best
        logger.info("found version %s on cache server, resolving sdist URL", version)

        pinned_req = Requirement(f"{req.name}=={version}")
        try:
            source_provider = sources.get_source_provider(
                ctx=self.ctx,
                req=pinned_req,
                sdist_server_url=resolver.PYPI_SERVER_URL,
                req_type=req_type,
            )
            sdist_results = resolver.find_all_matching_from_provider(
                source_provider, pinned_req
            )
            if sdist_results:
                logger.info(
                    "resolved sdist URL for %s==%s from source provider",
                    req.name,
                    version,
                )
                return [sdist_results[0]]
        except Exception as err:
            logger.warning(
                "failed to resolve sdist URL for %s==%s: %s",
                req.name,
                version,
                err,
            )

        logger.warning(
            "cache server has %s==%s but source provider returned no sdist",
            req.name,
            version,
        )
        return []

    def get_matching_versions(
        self,
        req: Requirement,
        pre_built: bool,
    ) -> list[tuple[str, Version]]:
        """Filter known versions by requirement specifier (thread-safe).

        Returns all known versions of the package that satisfy the
        requirement's version specifier, sorted highest-first.

        Args:
            req: Package requirement with version specifier
            pre_built: Whether looking for prebuilt or source resolution

        Returns:
            List of (url, version) tuples matching the specifier.
        """
        with self._lock:
            return self._get_matching_versions(req, pre_built)

    def _get_matching_versions(
        self,
        req: Requirement,
        pre_built: bool,
    ) -> list[tuple[str, Version]]:
        """Filter known versions (caller must hold ``self._lock``)."""
        key = (canonicalize_name(req.name), pre_built)
        versions = self._known_versions.get(key, {})
        matching = [
            (url, version)
            for version, url in versions.items()
            if version in req.specifier
        ]
        matching.sort(key=lambda x: x[1], reverse=True)
        return matching

    def extend_known_versions(
        self,
        req: Requirement,
        pre_built: bool,
        result: list[tuple[str, Version]],
    ) -> None:
        """Extend the known-versions cache and mark the rule as resolved (thread-safe).

        Merges new versions into the package-level cache. When a version
        already exists, a non-empty URL takes precedence over an empty one
        (graph-resolved placeholders are replaced by real download URLs).

        Used by Bootstrapper to cache git URL resolutions that are
        handled externally (outside this resolver).

        Args:
            req: Package requirement (used for name and rule tracking)
            pre_built: Whether this is a prebuilt or source resolution
            result: List of (url, version) tuples to add
        """
        with self._lock:
            self._extend_known_versions(req, pre_built, result)

    def _extend_known_versions(
        self,
        req: Requirement,
        pre_built: bool,
        result: list[tuple[str, Version]],
    ) -> None:
        """Extend known versions (caller must hold ``self._lock``)."""
        key = (canonicalize_name(req.name), pre_built)
        versions = self._known_versions.setdefault(key, {})
        for url, version in result:
            if version not in versions or (url and not versions[version]):
                versions[version] = url
        self._resolved_rules.add((str(req), pre_built))

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
            # find_all_matching_from_provider now returns all matching candidates
            return resolver.find_all_matching_from_provider(provider, req)
        except Exception as err:
            logger.debug(f"could not resolve {req} from {version_source}: {err}")
            return None
