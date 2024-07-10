import logging
import pathlib

import yaml

from . import overrides

logger = logging.getLogger(__name__)


class Settings:
    def __init__(self, data: dict):
        self._data = data

    def pre_built(self, variant: str) -> set[str]:
        p = self._data.get("pre_built") or {}
        names = p.get(variant) or []
        return set(overrides.pkgname_to_override_module(n) for n in names)

    def download_source(self) -> dict[str, dict[str, str]]:
        return self._data.get("download_source") or {}

    def sdist_download_url(self, pkg: str) -> str | None:
        p = self.download_source()
        download_source = p.get(pkg) or {}
        return download_source.get("url")

    def sdist_local_filename(self, pkg: str) -> str | None:
        p = self.download_source()
        download_source = p.get(pkg) or {}
        return download_source.get("rename_to")


def _parse(content: str) -> Settings:
    data = yaml.safe_load(content)
    return Settings(data)


def load(filename: pathlib.Path) -> Settings:
    filepath = pathlib.Path(filename)
    if not filepath.exists():
        logger.debug("settings file %s does not exist, ignoring", filepath.absolute())
        return Settings({})
    with open(filepath, "r") as f:
        logger.info("loading settings from %s", filepath.absolute())
        return _parse(f)
