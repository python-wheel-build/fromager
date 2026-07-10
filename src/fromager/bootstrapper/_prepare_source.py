from __future__ import annotations

import logging
import typing

from packaging.requirements import Requirement
from packaging.version import Version

from .. import build_environment, dependencies, sources
from ..log import req_ctxvar_context
from ..requirements_file import RequirementType, SourceType
from . import _cache
from ._phase import Phase
from ._prepare_build import PrepareBuild
from ._process_install_deps import ProcessInstallDeps
from ._types import BootstrapPhase, PreparedSourceData, SourceBuildResult

if typing.TYPE_CHECKING:
    from .. import context
    from ._bootstrapper import Bootstrapper

logger = logging.getLogger(__name__)


def _bg_prepare_source(
    ctx: context.WorkContext,
    cache_wheel_server_url: str | None,
    req: Requirement,
    resolved_version: Version,
    source_url: str,
) -> PreparedSourceData:
    """Background-safe source download+unpack: no Bootstrapper state accessed."""
    # Thread-safe: _seen_requirements in the main thread prevents the same
    # package from being submitted to the thread pool more than once.
    # Paths from download_source() and prepare_source() include {name}-{version},
    # making them unique across concurrent threads processing different packages.
    logger.info("preparing source")
    cached_wheel, unpacked = _cache._find_cached_wheel(
        ctx, cache_wheel_server_url, req, resolved_version
    )
    if unpacked is not None:
        return PreparedSourceData(
            sdist_root_dir=unpacked / unpacked.stem,
            cached_wheel_filename=cached_wheel,
        )
    source_filename = sources.download_source(
        ctx=ctx, req=req, version=resolved_version, download_url=source_url
    )
    sdist_root_dir = sources.prepare_source(
        ctx=ctx, req=req, source_filename=source_filename, version=resolved_version
    )
    return PreparedSourceData(sdist_root_dir=sdist_root_dir)


class PrepareSource(Phase):
    """Download the source distribution or prebuilt wheel and set up build-system deps.

    The download runs in a background thread (via ``background_work``).
    For prebuilt packages the background task fetches the wheel directly and
    the build phases are skipped entirely.  For source builds the background
    task downloads and unpacks the sdist; ``run()`` then reads build-system
    dependencies from the unpacked tree.

    Next phase:
    - Prebuilt wheel: ``ProcessInstallDeps``.
    - Source build: ``PrepareBuild`` + one ``Resolve`` per build-system dependency.
    """

    phase: typing.ClassVar[BootstrapPhase] = BootstrapPhase.PREPARE_SOURCE
    tracks_why: typing.ClassVar[bool] = True

    def background_work(
        self, bt: Bootstrapper
    ) -> typing.Callable[[], typing.Any] | None:
        """Return closure for background source download or prebuilt fetch."""
        wi = self.work_item
        assert wi.resolved_version is not None
        assert wi.source_url is not None
        ctx = bt.ctx
        cache_wheel_server_url = bt.cache_wheel_server_url
        req = wi.req
        req_type = wi.req_type
        resolved_version = wi.resolved_version
        source_url = wi.source_url

        if wi.pbi_pre_built:

            def do_prepare_prebuilt() -> PreparedSourceData:
                with req_ctxvar_context(req, resolved_version):
                    return _cache._bg_prepare_prebuilt(
                        ctx, req, req_type, resolved_version, source_url
                    )

            return do_prepare_prebuilt

        def do_prepare_source() -> PreparedSourceData:
            with req_ctxvar_context(req, resolved_version):
                return _bg_prepare_source(
                    ctx, cache_wheel_server_url, req, resolved_version, source_url
                )

        return do_prepare_source

    def run(self, bt: Bootstrapper) -> list[Phase]:
        """PREPARE_SOURCE phase: download source or prebuilt, get build system deps.

        Uses background I/O result from ``self.bg_future`` when available,
        falling back to inline I/O otherwise.

        Returns:
            Prebuilt: [ProcessInstallDeps] (skip build phases).
            Source: [PrepareBuild, *build_system_dep_items].
        """
        wi = self.work_item
        assert wi.resolved_version is not None
        assert wi.source_url is not None

        # bg_future is always set for PREPARE_SOURCE items (see _push_items).
        # bg_future.result() blocks until done and re-raises any background exception.
        assert self.bg_future is not None
        prepared: PreparedSourceData = self.bg_future.result()

        constraint = bt.ctx.constraints.get_constraint(wi.req.name)
        if constraint:
            logger.info(
                f"incoming requirement {wi.req} matches constraint "
                f"{constraint}. Will apply both."
            )

        if wi.pbi_pre_built:
            # Background task already downloaded the prebuilt wheel
            assert prepared.wheel_filename is not None
            assert prepared.unpack_dir is not None
            wi.build_result = SourceBuildResult(
                wheel_filename=prepared.wheel_filename,
                sdist_filename=None,
                unpack_dir=prepared.unpack_dir,
                sdist_root_dir=None,
                build_env=None,
                source_type=SourceType.PREBUILT,
            )
            return [ProcessInstallDeps(wi)]

        # Source build path: background task already downloaded and prepared the source
        assert prepared.sdist_root_dir is not None
        sdist_root_dir = prepared.sdist_root_dir
        wi.cached_wheel_filename = prepared.cached_wheel_filename

        assert sdist_root_dir is not None

        if sdist_root_dir.parent.parent != bt.ctx.work_dir:
            raise ValueError(f"'{sdist_root_dir}/../..' should be {bt.ctx.work_dir}")
        wi.sdist_root_dir = sdist_root_dir
        wi.unpack_dir = sdist_root_dir.parent

        wi.build_env = build_environment.BuildEnvironment(
            ctx=bt.ctx,
            parent_dir=sdist_root_dir.parent,
        )

        # Get build system dependencies
        wi.build_system_deps = dependencies.get_build_system_dependencies(
            ctx=bt.ctx,
            req=wi.req,
            version=wi.resolved_version,
            sdist_root_dir=sdist_root_dir,
        )

        dep_items: list[Phase] = bt.create_unresolved_work_items(
            wi.build_system_deps,
            RequirementType.BUILD_SYSTEM,
            wi.req,
            wi.resolved_version,
        )

        return [PrepareBuild(wi)] + dep_items
