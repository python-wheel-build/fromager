from __future__ import annotations

import logging
import typing

from .. import dependencies
from ..requirements_file import RequirementType
from ._build_item import BuildItem
from ._phase_item import PhaseItem
from ._types import BootstrapPhase

if typing.TYPE_CHECKING:
    from ._bootstrapper import Bootstrapper

logger = logging.getLogger(__name__)


class PrepareBuildItem(PhaseItem):
    """PREPARE_BUILD phase: install system deps, get backend/sdist deps."""

    phase: typing.ClassVar[BootstrapPhase] = BootstrapPhase.PREPARE_BUILD
    tracks_why: typing.ClassVar[bool] = True

    def run(self, bt: Bootstrapper) -> list[PhaseItem]:
        """PREPARE_BUILD phase: install system deps, get backend/sdist deps.

        Build-backend and build-sdist dependencies that are already satisfied
        by a resolved build-system dependency reuse that version instead of
        resolving independently (see :issue:`1194`).

        Returns:
            [BuildItem, *backend_dep_items, *sdist_dep_items].
        """
        wi = self.work_item
        assert wi.resolved_version is not None
        assert wi.build_env is not None
        assert wi.sdist_root_dir is not None

        # Install build system deps (their wheels exist from DFS processing)
        wi.build_env.install(wi.build_system_deps)

        # Get build backend dependencies
        wi.build_backend_deps = dependencies.get_build_backend_dependencies(
            ctx=bt.ctx,
            req=wi.req,
            version=wi.resolved_version,
            sdist_root_dir=wi.sdist_root_dir,
            build_env=wi.build_env,
        )

        # Get build sdist dependencies
        wi.build_sdist_deps = dependencies.get_build_sdist_dependencies(
            ctx=bt.ctx,
            req=wi.req,
            version=wi.resolved_version,
            sdist_root_dir=wi.sdist_root_dir,
            build_env=wi.build_env,
        )

        # Filter out deps already satisfied by build-system dependencies
        # to avoid resolving to a different (typically newer) version.
        resolved_build_sys = bt.get_resolved_build_system_versions(wi)
        parent = (wi.req, wi.resolved_version)
        wi.build_backend_deps = bt.filter_deps_satisfied_by_build_system(
            wi.build_backend_deps,
            resolved_build_sys,
            RequirementType.BUILD_BACKEND,
            parent,
        )
        wi.build_sdist_deps = bt.filter_deps_satisfied_by_build_system(
            wi.build_sdist_deps,
            resolved_build_sys,
            RequirementType.BUILD_SDIST,
            parent,
        )

        backend_items: list[PhaseItem] = bt.create_unresolved_work_items(
            wi.build_backend_deps,
            RequirementType.BUILD_BACKEND,
            wi.req,
            wi.resolved_version,
        )
        sdist_items: list[PhaseItem] = bt.create_unresolved_work_items(
            wi.build_sdist_deps,
            RequirementType.BUILD_SDIST,
            wi.req,
            wi.resolved_version,
        )
        dep_items = backend_items + sdist_items

        return [BuildItem(wi)] + dep_items
