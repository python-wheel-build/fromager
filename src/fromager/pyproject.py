"""Tooling for pyproject.toml"""

import logging
import pathlib
import typing

import tomlkit
from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name

from . import context

logger = logging.getLogger(__name__)

TomlDict = dict[str, typing.Any]

# section / key names
BUILD_SYSTEM = "build-system"
BUILD_BACKEND = "build-backend"
BUILD_REQUIRES = "requires"


class PyprojectFix:
    """Auto-fixer for pyproject.toml settings

    - add missing pyproject.toml
    - add or update `[build-system] requires`

    Requirements in `update_build_requires` are added to
    `[build-system] requires`. If a requirement name matches an existing
    name, then the requirement is replaced.

    Requirements in `remove_build_requires` are removed from
    `[build-system] requires`.
    """

    def __init__(
        self,
        req: Requirement,
        *,
        build_dir: pathlib.Path,
        update_build_requires: list[str],
        remove_build_requires: list[NormalizedName],
    ) -> None:
        self.req = req
        self.build_dir = build_dir
        self.update_requirements = update_build_requires
        self.remove_requirements = remove_build_requires
        self.pyproject_toml = self.build_dir / "pyproject.toml"
        self.setup_py = self.build_dir / "setup.py"

    def run(self) -> None:
        doc = self._load()
        build_system = self._default_build_system(doc)
        self._update_build_requires(build_system)
        logger.debug(
            "%s: pyproject.toml %s: %s=%r, %s=%r",
            self.req.name,
            BUILD_SYSTEM,
            BUILD_BACKEND,
            build_system.get(BUILD_BACKEND),
            BUILD_REQUIRES,
            build_system.get(BUILD_REQUIRES),
        )
        self._save(doc)

    def _load(self) -> tomlkit.TOMLDocument:
        """Load pyproject toml or create empty TOML doc"""
        try:
            doc = tomlkit.parse(self.pyproject_toml.read_bytes())
            logger.debug("%s: loaded pyproject.toml", self.req.name)
        except FileNotFoundError:
            logger.debug("%s: no pyproject.toml, create empty doc", self.req.name)
            doc = tomlkit.parse(b"")
        return doc

    def _save(self, doc: tomlkit.TOMLDocument) -> None:
        """Write pyproject.toml to build directory"""
        with self.pyproject_toml.open("w") as f:
            tomlkit.dump(doc, f)

    def _default_build_system(self, doc: tomlkit.TOMLDocument) -> TomlDict:
        """Add / fix basic 'build-system' dict"""
        build_system: TomlDict | None = doc.get(BUILD_SYSTEM)
        if build_system is None:
            logger.debug("%s: adding %s", self.req.name, BUILD_SYSTEM)
            build_system = doc.setdefault(BUILD_SYSTEM, {})
        # ensure `[build-system] requires` exists
        build_system.setdefault(BUILD_REQUIRES, [])
        return build_system

    def _update_build_requires(self, build_system: TomlDict) -> None:
        old_requires = build_system[BUILD_REQUIRES]
        # always include setuptools
        req_map: dict[NormalizedName, Requirement] = {
            canonicalize_name("setuptools"): Requirement("setuptools"),
        }
        # parse original build reqirements (if available)
        for reqstr in old_requires:
            req = Requirement(reqstr)
            req_map[canonicalize_name(req.name)] = req
        # remove unwanted requirements
        for name in self.remove_requirements:
            req_map.pop(canonicalize_name(name), None)
        # add / update requirements
        for reqstr in self.update_requirements:
            req = Requirement(reqstr)
            req_map[canonicalize_name(req.name)] = req

        new_requires = sorted(str(req) for req in req_map.values())
        if set(new_requires) != set(old_requires):
            # ignore order of items
            build_system[BUILD_REQUIRES] = new_requires
            logger.info(
                "%s: changed build-system requires from %r to %r",
                self.req.name,
                old_requires,
                new_requires,
            )


def apply_project_override(
    ctx: context.WorkContext, req: Requirement, sdist_root_dir: pathlib.Path
) -> None:
    """Apply project_overrides"""
    pbi = ctx.package_build_info(req)
    update_build_requires = pbi.project_override.update_build_requires
    remove_build_requires = pbi.project_override.remove_build_requires
    if update_build_requires or remove_build_requires:
        logger.debug(
            f"{req.name}: applying project_override: "
            f"{update_build_requires=}, {remove_build_requires=}"
        )
        build_dir = pbi.build_dir(sdist_root_dir)
        PyprojectFix(
            req,
            build_dir=build_dir,
            update_build_requires=update_build_requires,
            remove_build_requires=remove_build_requires,
        ).run()
    else:
        logger.debug(f"{req.name}: no project_override")
