from __future__ import annotations

import logging
import pathlib
import typing

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from .. import build_environment, dependencies, hooks
from ..requirements_file import RequirementType
from ._complete_item import CompleteItem
from ._phase_item import PhaseItem
from ._types import BootstrapPhase

if typing.TYPE_CHECKING:
    from .. import context
    from ._bootstrapper import Bootstrapper

logger = logging.getLogger(__name__)


def _get_install_dependencies(
    ctx: context.WorkContext,
    req: Requirement,
    resolved_version: Version,
    wheel_filename: pathlib.Path | None,
    sdist_filename: pathlib.Path | None,
    sdist_root_dir: pathlib.Path | None,
    build_env: build_environment.BuildEnvironment | None,
    unpack_dir: pathlib.Path | None,
) -> list[Requirement]:
    """Extract install dependencies from a built wheel or sdist.

    Returns:
        List of install requirements.

    Raises:
        RuntimeError: If both wheel_filename and sdist_filename are None.
    """
    if wheel_filename is not None:
        assert unpack_dir is not None
        logger.debug(
            "get install dependencies of wheel %s",
            wheel_filename.name,
        )
        return list(
            dependencies.get_install_dependencies_of_wheel(
                req=req,
                wheel_filename=wheel_filename,
                requirements_file_dir=unpack_dir,
            )
        )
    elif sdist_filename is not None:
        assert sdist_root_dir is not None
        assert build_env is not None
        logger.debug(
            "get install dependencies of sdist from directory %s",
            sdist_root_dir,
        )
        return list(
            dependencies.get_install_dependencies_of_sdist(
                ctx=ctx,
                req=req,
                version=resolved_version,
                sdist_root_dir=sdist_root_dir,
                build_env=build_env,
            )
        )
    else:
        raise RuntimeError("wheel_filename and sdist_filename are None")


class ProcessInstallDepsItem(PhaseItem):
    """PROCESS_INSTALL_DEPS phase: hooks, extract deps, build order."""

    phase: typing.ClassVar[BootstrapPhase] = BootstrapPhase.PROCESS_INSTALL_DEPS
    tracks_why: typing.ClassVar[bool] = True

    def run(self, bt: Bootstrapper) -> list[PhaseItem]:
        """PROCESS_INSTALL_DEPS phase: hooks, extract deps, build order.

        Returns:
            [CompleteItem, *install_dep_items].
        """
        wi = self.work_item
        assert wi.resolved_version is not None
        assert wi.source_url is not None
        assert wi.build_result is not None

        # Run post-bootstrap hooks (non-fatal in test mode)
        try:
            hooks.run_post_bootstrap_hooks(
                ctx=bt.ctx,
                req=wi.req,
                dist_name=canonicalize_name(wi.req.name),
                dist_version=str(wi.resolved_version),
                sdist_filename=wi.build_result.sdist_filename,
                wheel_filename=wi.build_result.wheel_filename,
            )
        except Exception as hook_error:
            if not bt.test_mode:
                raise
            bt.record_test_mode_failure(
                wi.req,
                str(wi.resolved_version),
                hook_error,
                "hook",
                "warning",
            )

        # Extract install dependencies (non-fatal in test mode)
        try:
            install_dependencies = _get_install_dependencies(
                ctx=bt.ctx,
                req=wi.req,
                resolved_version=wi.resolved_version,
                wheel_filename=wi.build_result.wheel_filename,
                sdist_filename=wi.build_result.sdist_filename,
                sdist_root_dir=wi.build_result.sdist_root_dir,
                build_env=wi.build_result.build_env,
                unpack_dir=wi.build_result.unpack_dir,
            )
        except Exception as dep_error:
            if not bt.test_mode:
                raise
            bt.record_test_mode_failure(
                wi.req,
                str(wi.resolved_version),
                dep_error,
                "dependency_extraction",
                "warning",
            )
            install_dependencies = []

        logger.debug(
            "install dependencies: %s",
            ", ".join(sorted(str(r) for r in install_dependencies)),
        )

        pbi = bt.ctx.package_build_info(wi.req)
        constraint = bt.ctx.constraints.get_constraint(wi.req.name)
        bt.add_to_build_order(
            req=wi.req,
            version=wi.resolved_version,
            source_url=wi.source_url,
            source_type=wi.build_result.source_type,
            prebuilt=pbi.pre_built,
            constraint=constraint,
        )

        dep_items: list[PhaseItem] = bt.create_unresolved_work_items(
            install_dependencies,
            RequirementType.INSTALL,
            wi.req,
            wi.resolved_version,
        )

        return [CompleteItem(wi)] + dep_items
