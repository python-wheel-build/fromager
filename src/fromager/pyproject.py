"""Tooling for pyproject.toml"""

import ast
import logging
import pathlib
import sys
import typing

import tomlkit
from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name

if typing.TYPE_CHECKING:
    from . import context

logger = logging.getLogger(__name__)

TomlDict = dict[str, typing.Any]

# section / key names
BUILD_SYSTEM = "build-system"
BUILD_BACKEND = "build-backend"
BUILD_REQUIRES = "requires"


class PyprojectOverrides(typing.NamedTuple):
    """pyproject.toml overrides

    import_build_requires: auto detect imports in setup.py
    drop_build_requires: remove packages from [build-system]requires
    replace_build_requires: replace a build requirement with another
    """

    enable: bool
    auto_build_requires: dict[str, Requirement]
    remove_build_requires: list[NormalizedName]
    replace_build_requires: dict[NormalizedName, Requirement]

    @classmethod
    def from_dict(cls, overrides: dict[str, typing.Any]) -> "PyprojectOverrides":
        result = PyprojectOverrides(bool(overrides.get("enable", False)), {}, [], {})

        if overrides.get("auto_build_requires"):
            for name, reqstr in overrides["auto_build_requires"].items():
                result.auto_build_requires[name] = Requirement(reqstr)

        if overrides.get("remove_build_requires"):
            for name in overrides["remove_build_requires"]:
                result.remove_build_requires.append(canonicalize_name(name))

        if overrides.get("replace_build_requires"):
            for name, reqstr in overrides["replace_build_requires"].items():
                result.replace_build_requires[canonicalize_name(name)] = Requirement(
                    reqstr
                )

        return result


class PyprojectFixer:
    """Auto-fixer for pyproject.toml

    - add missing pyproject.toml
    - add or update [build-system] map
    - detect additional build requirements by parsing "setup.py"
    - remove unwanted build requirements such as cmake
    """

    def __init__(
        self, ctx: "context.WorkContext", req: Requirement, sdist_root_dir: pathlib.Path
    ) -> None:
        self.overrides = ctx.settings.get_pypyproject_overrides()
        self.req = req
        self.root = sdist_root_dir
        self.pyproject_toml = self.root / "pyproject.toml"
        self.setup_py = self.root / "setup.py"

    def update(self):
        doc = self.load()
        build_system = self.default_builds_system(doc)
        self.update_build_requires(build_system)
        logger.debug(
            "%s: pyproject.toml %s: %s=%r, %s=%r",
            self.name,
            BUILD_SYSTEM,
            BUILD_BACKEND,
            build_system.get(BUILD_BACKEND),
            BUILD_REQUIRES,
            build_system.get(BUILD_REQUIRES),
        )
        self.save(doc)

    @property
    def name(self) -> str:
        return self.req.name

    def load(self) -> tomlkit.TOMLDocument:
        try:
            doc = tomlkit.parse(self.pyproject_toml.read_bytes())
            logger.debug("%s: loaded pyproject.toml", self.name)
        except FileNotFoundError:
            logger.debug("%s: no pyproject.toml, create empty doc", self.name)
            doc = tomlkit.parse(b"")
        return doc

    def save(self, doc: tomlkit.TOMLDocument) -> None:
        with self.pyproject_toml.open("w") as f:
            tomlkit.dump(doc, f)

    def default_builds_system(self, doc: tomlkit.TOMLDocument) -> TomlDict:
        """Add / fix basic 'build-system' dict"""
        build_system: TomlDict | None = doc.get(BUILD_SYSTEM)
        if build_system is None:
            logger.debug("%s: adding %s", self.name, BUILD_SYSTEM)
            build_system = doc.setdefault(BUILD_SYSTEM, {})
        # Do not add build backend. A package build without a build backend
        # option behaves differently than with 'setuptools.build_meta'.
        if BUILD_REQUIRES not in build_system:
            # default to setuptools
            build_system[BUILD_REQUIRES] = ["setuptools"]
            logger.debug(
                "%s: adding %s = %s",
                self.name,
                BUILD_REQUIRES,
                build_system[BUILD_REQUIRES],
            )
        return build_system

    def update_build_requires(self, build_system: TomlDict) -> None:
        # always add setuptools
        add: list[Requirement] = [Requirement("setuptools")]

        for name in self._analyze_setup_imports():
            if name == "distutils":
                # special case, distutils is deprecated
                add.append(
                    self.overrides.replace_build_requires.get(
                        NormalizedName("setuptools"),
                        Requirement("setuptools"),
                    )
                )
            elif name in sys.stdlib_module_names:
                # nothing to do for stdlib modules
                continue
            else:
                req: Requirement | None = self.overrides.auto_build_requires.get(name)
                if req is not None:
                    add.append(req)

        build_system[BUILD_REQUIRES] = self._modify_build_requires(
            build_system[BUILD_REQUIRES],
            add,
        )

    def _modify_build_requires(
        self,
        old_requires: list[str],
        add: typing.Sequence[Requirement] = (),
    ) -> list[str]:
        """Fix basic requirements (setuptools, wheel, packaging)"""
        req_map: dict[NormalizedName, Requirement] = {}
        for reqstr in old_requires:
            req = Requirement(reqstr)
            req_map[canonicalize_name(req.name)] = req

        for req in add:
            # keep existing
            req_map.setdefault(canonicalize_name(req.name), req)

        for name in self.overrides.remove_build_requires:
            req_map.pop(name, None)

        for name, req in self.overrides.replace_build_requires.items():
            if name in req_map:
                req_map[name] = req

        new_requires = sorted(str(req) for req in req_map.values())
        logger.debug(
            "%s: changed build-system requires from %r to %r",
            self.name,
            old_requires,
            new_requires,
        )
        return new_requires

    def _analyze_setup_imports(self) -> typing.Iterable[str]:
        """Analyze setup.py and return import names"""
        try:
            content = self.setup_py.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        modules = []
        rootnode = ast.parse(content, str(self.setup_py))
        for node in ast.walk(rootnode):
            if isinstance(node, ast.Import):
                for subnode in node.names:
                    modules.append(subnode.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.append(node.module)
        # top-level names
        return [name.split(".", 1)[0] for name in modules]
