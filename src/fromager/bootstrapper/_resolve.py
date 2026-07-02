from __future__ import annotations

import logging
import typing

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from .. import bootstrap_requirement_resolver
from ..log import req_ctxvar_context
from ..requirements_file import RequirementType
from . import _cache
from ._phase import Phase
from ._start import Start
from ._types import BootstrapPhase
from ._work_item import WorkItem

if typing.TYPE_CHECKING:
    from ._bootstrapper import Bootstrapper

logger = logging.getLogger(__name__)


def _bg_resolve(
    bg_resolver: bootstrap_requirement_resolver.BootstrapRequirementResolver,
    req: Requirement,
    req_type: RequirementType,
    parent_req: Requirement | None,
    return_all_versions: bool,
) -> list[tuple[str, Version]]:
    """Background-safe resolution: no Bootstrapper state accessed."""
    logger.info(f"{BootstrapPhase.RESOLVE} for {req_type} requirement")
    return bg_resolver.resolve(
        req=req,
        req_type=req_type,
        parent_req=parent_req,
        return_all_versions=return_all_versions,
    )


class Resolve(Phase):
    """RESOLVE phase: resolve versions and expand into Start items."""

    phase: typing.ClassVar[BootstrapPhase] = BootstrapPhase.RESOLVE
    tracks_why: typing.ClassVar[bool] = False

    def background_work(
        self, bt: Bootstrapper
    ) -> typing.Callable[[], typing.Any] | None:
        """Return closure that calls ``_bg_resolve`` in a thread."""
        bg_resolver = bt.resolver
        req = self.work_item.req
        req_type = self.work_item.req_type
        parent_req = (
            self.work_item.why_snapshot[-1][1] if self.work_item.why_snapshot else None
        )
        return_all = bt.multiple_versions

        def do_resolve() -> list[tuple[str, Version]]:
            with req_ctxvar_context(req):
                return _bg_resolve(bg_resolver, req, req_type, parent_req, return_all)

        return do_resolve

    def run(self, bt: Bootstrapper) -> list[Phase]:
        """RESOLVE phase: resolve versions and expand into Start items.

        Centralizes version resolution so all dependencies are expanded
        uniformly. In multiple_versions mode, filters out versions that
        already failed in this run and versions whose wheels are already
        cached to avoid redundant builds and transitive dependency
        processing.

        Returns:
            One Start item per resolved version that needs building.
            Empty list if all versions are already cached.
        """
        assert self.bg_future is not None
        # bg_future.result() blocks until the background resolution completes,
        # then returns the result or re-raises any exception from the background.
        resolved_versions = self.bg_future.result()
        if not resolved_versions:
            raise RuntimeError(
                f"Could not resolve any versions for {self.work_item.req}"
            )

        if bt.multiple_versions:
            pkg_name = canonicalize_name(self.work_item.req.name)
            resolved_versions = [
                (url, ver)
                for url, ver in resolved_versions
                if not bt.has_failed_version(pkg_name, ver)
            ]
            if not resolved_versions:
                raise RuntimeError(
                    f"Could not resolve any versions for {self.work_item.req}"
                    f" (all candidates failed previously)"
                )

            logger.info(
                f"resolved {len(resolved_versions)} version(s) for {self.work_item.req}"
            )
            filtered: list[tuple[str, Version]] = []
            for source_url, version in resolved_versions:
                cached_wheel, _ = _cache._find_cached_wheel(
                    bt.ctx, bt.cache_wheel_server_url, self.work_item.req, version
                )
                if cached_wheel:
                    logger.info(
                        f"{self.work_item.req.name}=={version}: wheel already cached "
                        f"at {cached_wheel.name}, skipping"
                    )
                else:
                    filtered.append((source_url, version))
            if not filtered:
                # Always process the highest version (first in
                # resolved_versions) so new transitive dependencies
                # are discovered even when every wheel is cached.
                logger.info(
                    f"all versions of {self.work_item.req.name} already cached, "
                    f"keeping highest version {resolved_versions[0][1]} "
                    f"for dependency discovery"
                )
                filtered.append(resolved_versions[0])
            resolved_versions = filtered

        # Build list so highest version ends up on top of the stack
        # (last element after extend) and is processed first.
        items: list[Phase] = []
        for source_url, version in reversed(resolved_versions):
            items.append(
                Start(
                    WorkItem(
                        req=self.work_item.req,
                        req_type=self.work_item.req_type,
                        why_snapshot=list(self.work_item.why_snapshot),
                        parent=self.work_item.parent,
                        source_url=source_url,
                        resolved_version=version,
                    )
                )
            )
        return items
