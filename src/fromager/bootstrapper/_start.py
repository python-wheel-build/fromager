from __future__ import annotations

import logging
import typing

from ..requirements_file import RequirementType
from ._phase import Phase
from ._prepare_source import PrepareSource
from ._types import BootstrapPhase

if typing.TYPE_CHECKING:
    from ._bootstrapper import Bootstrapper

logger = logging.getLogger(__name__)


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

        # Add to graph (skip TOP_LEVEL, already added in _resolve_and_add_top_level)
        if wi.req_type != RequirementType.TOP_LEVEL:
            bt.add_to_graph(
                wi.req,
                wi.req_type,
                wi.resolved_version,
                wi.source_url,
                wi.parent,
            )

        wi.build_sdist_only = bt.sdist_only and not wi.is_build_requirement_context()

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

        # Must set pbi_pre_built before constructing PrepareSource so that
        # PrepareSource.background_work() immediately sees the correct value.
        pbi = bt.ctx.package_build_info(wi.req)
        wi.pbi_pre_built = pbi.pre_built
        wi.exclusive_build = pbi.exclusive_build
        return [PrepareSource(wi)]
