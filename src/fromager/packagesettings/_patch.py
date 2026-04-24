from __future__ import annotations

import logging
import pathlib
import re
import typing

import pydantic
from packaging.requirements import Requirement
from packaging.version import Version

from ..pyproject import PyprojectFix
from ._typedefs import (
    MODEL_CONFIG,
    Package,
    SpecifierSetType,
)

if typing.TYPE_CHECKING:
    from .. import build_environment, context

logger = logging.getLogger(__name__)

SDIST_STEP = typing.Literal["sdist"]
DIST_INFO_METADATA_STEP = typing.Literal["dist-info-metadata"]


class PatchBase(pydantic.BaseModel):
    """Base class for patch setting"""

    model_config = MODEL_CONFIG

    step: typing.ClassVar[SDIST_STEP | DIST_INFO_METADATA_STEP]
    """In which step of the build process does the plugin run?

    - ``sdist`` plugins run between unpackagin and repacking of source
      distributions
    - ``dist-info-metadata`` run when the final wheel file is assembled.
      They also affect ``get_install_dependencies_of_sdist`` hook.
    """

    op: str
    """Operation name (discriminator field)"""

    title: str
    """Human-readable title for the config setting"""

    when_version: SpecifierSetType | None = None
    """Only patch when specifer set matches"""

    ignore_missing: bool = False
    """Don't fail when operation does not modify a file"""


class SdistPatchBase(PatchBase):
    """Base class for patching of sdists"""

    step = "sdist"

    def __call__(
        self,
        *,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        sdist_root_dir: pathlib.Path,
    ) -> None:
        raise NotImplementedError


class PatchReplaceLine(SdistPatchBase):
    """Replace line in sources"""

    op: typing.Literal["replace-line"]
    files: typing.Annotated[list[str], pydantic.Field(min_length=1)]
    search: re.Pattern
    replace: str

    def __call__(
        self,
        *,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        sdist_root_dir: pathlib.Path,
    ) -> None:
        # TODO
        raise NotImplementedError


class PatchDeleteLine(SdistPatchBase):
    """Delete line in sources"""

    op: typing.Literal["delete-line"]
    files: typing.Annotated[list[str], pydantic.Field(min_length=1)]
    search: re.Pattern

    def __call__(
        self,
        *,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        sdist_root_dir: pathlib.Path,
    ) -> None:
        # TODO
        raise NotImplementedError


class PatchPyProjectBuildSystem(SdistPatchBase):
    """Modify pyproject.toml [build-system]

    Replaces project_override setting
    """

    op: typing.Literal["pyproject-build-system"]

    update_build_requires: list[str] = pydantic.Field(default_factory=list)
    """Add / update requirements to pyproject.toml `[build-system] requires`
    """

    # TODO: use list[Package]
    remove_build_requires: list[Package] = pydantic.Field(default_factory=list)
    """Remove requirement from pyproject.toml `[build-system] requires`
    """

    requires_external: list[str] = pydantic.Field(default_factory=list)
    """Add / update Requires-External core metadata field

    Each entry contains a string describing some dependency in the system
    that the distribution is to be used. See
    https://packaging.python.org/en/latest/specifications/core-metadata/#requires-external-multiple-use

    .. note::
       Fromager does not modify ``METADATA`` file, yet. Read the information
       from an ``importlib.metadata`` distribution with
       ``tomlkit.loads(dist(pkgname).read_text("fromager-build-settings"))``.
    """

    @pydantic.field_validator("update_build_requires")
    @classmethod
    def validate_update_build_requires(cls, v: list[str]) -> list[str]:
        """update_build_requires fields must be valid requirements"""
        for reqstr in v:
            Requirement(reqstr)
        return v

    def __call__(
        self,
        *,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        sdist_root_dir: pathlib.Path,
    ) -> None:
        if self.update_build_requires or self.remove_build_requires:
            pbi = ctx.package_build_info(req)
            fixer = PyprojectFix(
                req,
                build_dir=pbi.build_dir(sdist_root_dir),
                update_build_requires=self.update_build_requires,
                remove_build_requires=self.remove_build_requires,
            )
            fixer.run()


class FixPkgInfoVersion(SdistPatchBase):
    """Fix PKG-INFO Metadata version of an sdist"""

    op: typing.Literal["fix-pkg-info"]
    metadata_version: str = "2.4"

    def __call__(
        self,
        *,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        sdist_root_dir: pathlib.Path,
    ) -> None:
        # TODO
        raise NotImplementedError


# ---------------------------------------------------------------------------


class DistInfoMetadataPatchBase(PatchBase):
    """Base class for patching of dist-info metadata

    The patchers affect wheel metadata and outcome of
    ``get_install_dependencies_of_sdist``.
    """

    step = "dist-info-metadata"

    def __call__(
        self,
        *,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        dist_info_dir: pathlib.Path,
        build_env: build_environment.BuildEnvironment,
    ) -> None:
        raise NotImplementedError


class PinRequiresDistToConstraint(DistInfoMetadataPatchBase):
    """Pin install requirements to constraint

    Update an installation requirement version and pin it to the same
    version as configured in constraints.
    """

    op: typing.Literal["pin-requires-dist-to-constraint"]
    requirements: typing.Annotated[list[Package], pydantic.Field(min_length=1)]

    def __call__(
        self,
        *,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        dist_info_dir: pathlib.Path,
        build_env: build_environment.BuildEnvironment,
    ) -> None:
        # TODO
        raise NotImplementedError


PatchUnion = typing.Annotated[
    PatchReplaceLine
    | PatchDeleteLine
    | PatchPyProjectBuildSystem
    | FixPkgInfoVersion
    | PinRequiresDistToConstraint,
    pydantic.Field(..., discriminator="op"),
]


class Patches(pydantic.RootModel[list[PatchUnion]]):
    def run_sdist_patcher(
        self,
        *,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        sdist_root_dir: pathlib.Path,
    ) -> None:
        for patcher in self.root:
            if patcher == SDIST_STEP:
                assert isinstance(patcher, SdistPatchBase)
                patcher(
                    ctx=ctx,
                    req=req,
                    version=version,
                    sdist_root_dir=sdist_root_dir,
                )

    def run_dist_info_metadata_patcher(
        self,
        *,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        dist_info_dir: pathlib.Path,
        build_env: build_environment.BuildEnvironment,
    ) -> None:
        for patcher in self.root:
            if patcher.step == DIST_INFO_METADATA_STEP:
                assert isinstance(patcher, DistInfoMetadataPatchBase)
                patcher(
                    ctx=ctx,
                    req=req,
                    version=version,
                    dist_info_dir=dist_info_dir,
                    build_env=build_env,
                )
