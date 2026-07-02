from __future__ import annotations

import logging
import pathlib
import typing

from .. import finders, server, sources, wheels
from ._phase_item import PhaseItem
from ._process_install_deps_item import ProcessInstallDepsItem
from ._types import BootstrapPhase, SourceBuildResult

if typing.TYPE_CHECKING:
    from .. import context
    from ._bootstrapper import Bootstrapper

logger = logging.getLogger(__name__)


class BuildItem(PhaseItem):
    """BUILD phase: install remaining deps, build wheel/sdist."""

    phase: typing.ClassVar[BootstrapPhase] = BootstrapPhase.BUILD
    tracks_why: typing.ClassVar[bool] = True

    @property
    def requires_exclusive_run(self) -> bool:
        return self.work_item.exclusive_build

    def run(self, bt: Bootstrapper) -> list[PhaseItem]:
        """BUILD phase: install remaining deps, build wheel/sdist.

        Returns:
            [ProcessInstallDepsItem].
        """
        wi = self.work_item
        assert wi.resolved_version is not None
        assert wi.build_env is not None
        assert wi.sdist_root_dir is not None

        # Install backend+sdist deps if disjoint from system deps
        remaining_deps = wi.build_backend_deps | wi.build_sdist_deps
        if remaining_deps.isdisjoint(wi.build_system_deps):
            wi.build_env.install(remaining_deps)

        wheel_filename, sdist_filename = self.do_build(bt.ctx, bt.explain)

        source_type = sources.get_source_type(bt.ctx, wi.req)

        wi.build_result = SourceBuildResult(
            wheel_filename=wheel_filename,
            sdist_filename=sdist_filename,
            unpack_dir=wi.sdist_root_dir.parent,
            sdist_root_dir=wi.sdist_root_dir,
            build_env=wi.build_env,
            source_type=source_type,
        )

        return [ProcessInstallDepsItem(wi)]

    def _build_sdist(self, ctx: context.WorkContext) -> pathlib.Path:
        """Build or locate an sdist for this item's package.

        Checks ``ctx.sdists_builds`` for an existing sdist before invoking
        ``sources.build_sdist()``.
        """
        wi = self.work_item
        assert wi.resolved_version is not None
        assert wi.sdist_root_dir is not None
        assert wi.build_env is not None
        find_sdist_result = finders.find_sdist(
            ctx, ctx.sdists_builds, wi.req, str(wi.resolved_version)
        )
        if not find_sdist_result:
            sdist_filename: pathlib.Path = sources.build_sdist(
                ctx=ctx,
                req=wi.req,
                version=wi.resolved_version,
                sdist_root_dir=wi.sdist_root_dir,
                build_env=wi.build_env,
            )
        else:
            sdist_filename = find_sdist_result
            logger.info(
                f"have sdist version {wi.resolved_version}: {find_sdist_result}"
            )
        return sdist_filename

    def _build_wheel(
        self,
        ctx: context.WorkContext,
        explain: str = "",
    ) -> tuple[pathlib.Path, pathlib.Path]:
        """Build a wheel for this item's package.

        Calls :meth:`_build_sdist` first, then invokes ``wheels.build_wheel()``
        and updates the local wheel mirror. Returns ``(wheel_filename,
        sdist_filename)`` where *wheel_filename* is the path in
        ``ctx.wheels_downloads`` after the mirror update.
        """
        wi = self.work_item
        assert wi.resolved_version is not None
        assert wi.sdist_root_dir is not None
        assert wi.build_env is not None
        sdist_filename = self._build_sdist(ctx)

        logger.info(f"starting build of {explain} for {ctx.variant}")
        built_filename = wheels.build_wheel(
            ctx=ctx,
            req=wi.req,
            sdist_root_dir=wi.sdist_root_dir,
            version=wi.resolved_version,
            build_env=wi.build_env,
        )
        server.update_wheel_mirror(ctx)
        # When we update the mirror, the built file moves to the downloads directory.
        wheel_filename = ctx.wheels_downloads / built_filename.name
        logger.info(f"built wheel for version {wi.resolved_version}: {wheel_filename}")
        return wheel_filename, sdist_filename

    def do_build(
        self,
        ctx: context.WorkContext,
        explain: str = "",
    ) -> tuple[pathlib.Path | None, pathlib.Path | None]:
        """Build a wheel or sdist for this item's package.

        Returns ``(wheel_filename, sdist_filename)``.  Either value may be
        ``None`` depending on the build path:

        - Cached wheel:  ``(cached_wheel_filename, None)``
        - sdist-only:    ``(None, sdist_filename)``
        - Full wheel:    ``(wheel_filename, sdist_filename)``
        """
        wi = self.work_item
        if wi.cached_wheel_filename:
            logger.debug(
                f"getting install requirements from cached wheel {wi.cached_wheel_filename.name}"
            )
            return wi.cached_wheel_filename, None
        elif wi.build_sdist_only:
            logger.debug(
                f"getting install requirements from sdist {wi.req.name}=={wi.resolved_version}"
            )
            return None, self._build_sdist(ctx)
        else:
            logger.debug(
                f"building wheel {wi.req.name}=={wi.resolved_version} to get install requirements"
            )
            return self._build_wheel(ctx, explain)
