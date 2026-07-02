from __future__ import annotations

import dataclasses
import logging
import pathlib

from packaging.requirements import Requirement
from packaging.version import Version

from .. import build_environment
from ..requirements_file import RequirementType
from ._types import SourceBuildResult

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class WorkItem:
    """A unit of work in the iterative bootstrap loop.

    Carries identity fields set at creation time and accumulated state
    populated across phases as processing advances. The current phase is
    encoded by the ``Phase`` subclass wrapping this object.

    Items enter at the RESOLVE phase with only req and req_type set.
    The RESOLVE phase populates source_url and resolved_version, then
    creates new items at the START phase for each resolved version.
    """

    # Identity (set at creation)
    req: Requirement
    req_type: RequirementType
    why_snapshot: list[tuple[RequirementType, Requirement, Version]]
    parent: tuple[Requirement, Version] | None = None

    # Populated by RESOLVE phase (None until then)
    source_url: str | None = None
    resolved_version: Version | None = None

    build_sdist_only: bool = False

    # Accumulated state (populated during phases)
    build_env: build_environment.BuildEnvironment | None = None
    sdist_root_dir: pathlib.Path | None = None
    unpack_dir: pathlib.Path | None = None
    cached_wheel_filename: pathlib.Path | None = None
    build_result: SourceBuildResult | None = None
    pbi_pre_built: bool = False
    exclusive_build: bool = False
    build_system_deps: set[Requirement] = dataclasses.field(default_factory=set)
    build_backend_deps: set[Requirement] = dataclasses.field(default_factory=set)
    build_sdist_deps: set[Requirement] = dataclasses.field(default_factory=set)

    def is_build_requirement_context(self) -> bool:
        """Return True if this item is being processed as part of a build requirement.

        A package is a build dependency if its own requirement type is
        build_system, build_backend, or build_sdist, OR if it is an install
        requirement of something that is itself a build dependency (checked
        by walking the ``why_snapshot`` chain).
        """
        if self.req_type.is_build_requirement:
            logger.debug(f"is itself a build requirement: {self.req_type}")
            return True
        if not self.req_type.is_install_requirement:
            logger.debug(
                "is not an install requirement, not checking dependency chain for a build requirement"
            )
            return False
        for req_type, req, resolved_version in reversed(self.why_snapshot):
            if req_type.is_build_requirement:
                logger.debug(
                    f"is a build requirement because {req_type} dependency {req} ({resolved_version}) depends on it"
                )
                return True
        logger.debug("is not a build requirement")
        return False
