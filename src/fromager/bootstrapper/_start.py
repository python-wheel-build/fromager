from __future__ import annotations

import logging
import typing

from packaging.requirements import Requirement
from packaging.version import Version

from .. import resolver, sources, wheels
from ..requirements_file import RequirementType
from ._phase import Phase
from ._prepare_source import PrepareSource
from ._types import BootstrapPhase

if typing.TYPE_CHECKING:
    from .. import context
    from ._bootstrapper import Bootstrapper

logger = logging.getLogger(__name__)


def _re_resolve_url(
    ctx: context.WorkContext,
    req: Requirement,
    req_type: RequirementType,
    resolved_version: Version,
    pre_built: bool,
    cache_wheel_server_url: str | None,
) -> str | None:
    """Re-resolve the download URL when version-specific pre_built differs.

    Returns the new URL or ``None`` if re-resolution fails.
    """
    pinned_req = Requirement(f"{req.name}=={resolved_version}")
    if pre_built:
        wheel_server_urls = wheels.get_wheel_server_urls(
            ctx,
            req,
            cache_wheel_server_url=cache_wheel_server_url,
            version=resolved_version,
        )
        try:
            url, _ = wheels.resolve_prebuilt_wheel(
                ctx=ctx,
                req=pinned_req,
                wheel_server_urls=wheel_server_urls,
                req_type=req_type,
            )
        except ExceptionGroup:
            return None
        return str(url)
    else:
        pbi = ctx.package_build_info(req)
        sdist_server = pbi.resolver_sdist_server_url(resolver.PYPI_SERVER_URL)
        provider = sources.get_source_provider(
            ctx=ctx,
            req=pinned_req,
            sdist_server_url=sdist_server,
            req_type=req_type,
        )
        results = resolver.find_all_matching_from_provider(provider, pinned_req)
        if results:
            return str(results[0][0])
        return None


class Start(Phase):
    """Record a resolved requirement in the dependency graph and deduplicate.

    Adds the ``(parent → req)`` edge to the dependency graph, then checks
    whether this ``(req, version)`` pair has already been processed.  Duplicate
    requirements are silently dropped; new ones proceed to source preparation.
    ``tracks_why`` is ``False`` so graph additions happen before the why-stack
    is updated.

    Next phase: ``PrepareSource`` (new requirement) or ``[]`` (already seen).
    """

    phase: typing.ClassVar[BootstrapPhase] = BootstrapPhase.START
    tracks_why: typing.ClassVar[bool] = False

    def run(self, bt: Bootstrapper) -> list[Phase]:
        """START phase: add to graph, check if already seen.

        _track_why is a no-op for this phase (tracks_why is False),
        matching the original behavior where graph addition and
        seen-check happen before pushing onto the why stack.

        Returns:
            Empty list if already seen (nothing to do).
            [PrepareSource] if this is new work.
        """
        wi = self.work_item
        assert wi.resolved_version is not None
        assert wi.source_url is not None

        wi.build_sdist_only = bt.sdist_only and not wi.is_build_requirement_context()

        # Must set pbi_pre_built before constructing PrepareSource so that
        # PrepareSource.background_work() immediately sees the correct value.
        pbi = bt.ctx.package_build_info(wi.req)
        wi.pbi_pre_built = pbi.is_pre_built(wi.resolved_version)
        wi.exclusive_build = pbi.exclusive_build

        # Re-resolve URL before graph insertion so the graph stores the
        # final URL, and before the seen-check so duplicate parents still
        # get their edge recorded with the correct URL.
        version_url = pbi.get_wheel_server_url(wi.resolved_version)
        variant_url = pbi.wheel_server_url
        needs_re_resolve = wi.pbi_pre_built != pbi.pre_built or (
            wi.pbi_pre_built and version_url != variant_url
        )
        if needs_re_resolve:
            logger.info(
                f"{wi.req} {wi.resolved_version}: version-specific override "
                f"(pre_built={wi.pbi_pre_built}, url={version_url}) differs "
                f"from variant default, re-resolving URL"
            )
            new_url = _re_resolve_url(
                bt.ctx,
                wi.req,
                wi.req_type,
                wi.resolved_version,
                wi.pbi_pre_built,
                bt.cache_wheel_server_url,
            )
            if new_url is not None:
                wi.source_url = new_url
            else:
                logger.warning(
                    f"{wi.req} {wi.resolved_version}: could not re-resolve URL "
                    f"for pre_built={wi.pbi_pre_built}, using original"
                )

        # Add to graph after URL finalization but before the seen-check
        # so every parent-to-dep edge is recorded with the correct URL.
        if wi.req_type != RequirementType.TOP_LEVEL:
            bt.add_to_graph(
                wi.req,
                wi.req_type,
                wi.resolved_version,
                wi.source_url,
                wi.parent,
            )

        if bt.has_been_seen(wi.req, wi.resolved_version, wi.build_sdist_only):
            logger.debug(
                f"redundant {wi.req_type} dependency {wi.req} "
                f"({wi.resolved_version}, sdist_only={wi.build_sdist_only}) "
                f"for {bt.explain}"
            )
            return []
        bt.mark_as_seen(wi.req, wi.resolved_version, wi.build_sdist_only)

        logger.info(
            f"new {wi.req_type} dependency {wi.req} resolves to {wi.resolved_version}"
        )

        return [PrepareSource(wi)]
