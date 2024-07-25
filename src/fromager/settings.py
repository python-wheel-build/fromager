import logging
import pathlib
import typing

import yaml
from packaging.utils import NormalizedName, canonicalize_name

from . import overrides

logger = logging.getLogger(__name__)


class DownloadSource(typing.NamedTuple):
    url: str | None = None
    rename_to: str | None = None


class BuildOption(typing.NamedTuple):
    # scale parallel jobs by available CPU cores
    # 1: as many parallel jobs as CPU cores
    # 2: os.cpu_count() // 2
    cpu_scaling: int | None = None
    # scale parallel jobs by memory
    # 2: assume that each parallel job requires 2 GB max memory
    memory_scaling: int | None = None


class _Data(typing.TypedDict):
    pre_built: dict[str, set[NormalizedName]]
    download_source: dict[str, DownloadSource]
    build_option: dict[str, BuildOption]


class Settings:
    def __init__(self, data: dict):
        self._data: _Data = {
            "pre_built": {},
            "download_source": {},
            "build_option": {},
        }

        # variant -> set of canonicalized package names
        pre_built: dict[str, typing.Sequence[str]] = data.get("pre_built") or {}
        self._data["pre_built"] = {
            variant: set(canonicalize_name(p) for p in packages)
            for variant, packages in pre_built.items()
        }

        # canon package -> DownloadSource
        download_source: dict[str, dict[str, str]] = data.get("download_source") or {}
        self._data["download_source"] = {
            canonicalize_name(package): DownloadSource(**info)
            for package, info in download_source.items()
        }

        # canon package -> BuildOption
        build_option: dict[str, dict[str, typing.Any]] = data.get("build_option") or {}
        self._data["build_option"] = {
            canonicalize_name(package): BuildOption(**info)
            for package, info in build_option.items()
        }

    def pre_built(self, variant: str) -> set[str]:
        names = self._data["pre_built"].get(variant, set())
        return set(overrides.pkgname_to_override_module(n) for n in names)

    def download_source(self) -> dict[str, DownloadSource]:
        return self._data["download_source"]

    def _get_pkg_ds(self, pkg: str) -> DownloadSource | None:
        pkg = canonicalize_name(pkg)
        return self.download_source().get(pkg, None)

    def sdist_download_url(self, pkg: str) -> str | None:
        ds = self._get_pkg_ds(pkg)
        if ds:
            return ds.url
        return None

    def sdist_local_filename(self, pkg: str) -> str | None:
        ds = self._get_pkg_ds(pkg)
        if ds:
            return ds.rename_to
        return None

    def build_option(self, pkg: str) -> BuildOption | None:
        pkg = canonicalize_name(pkg)
        build_option = self._data["build_option"]
        return build_option.get(pkg)


def _parse(content: str) -> Settings:
    data = yaml.safe_load(content)
    return Settings(data)


def load(filename: pathlib.Path) -> Settings:
    filepath = pathlib.Path(filename)
    if not filepath.exists():
        logger.debug("settings file %s does not exist, ignoring", filepath.absolute())
        return Settings({})
    with filepath.open(encoding="utf-8") as f:
        logger.info("loading settings from %s", filepath.absolute())
        return _parse(f.read())
