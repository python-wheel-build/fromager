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

    def packages(self) -> dict[str, dict[str, str]]:
        p = self._return_value_or_default(self._data.get("packages"), {})
        return {
            overrides.pkgname_to_override_module(key): value for key, value in p.items()
        }

    def download_source_url(self, pkg: str, default: str | None = None) -> str | None:
        download_source = self._get_package_download_source_settings(pkg)
        return self._return_value_or_default(download_source.get("url"), default)

    def download_source_destination_filename(
        self, pkg: str, default: str | None = None
    ) -> str | None:
        download_source = self._get_package_download_source_settings(pkg)
        return self._return_value_or_default(
            download_source.get("destination_filename"), default
        )

    def resolver_sdist_server_url(
        self, pkg: str, default: str | None = None
    ) -> str | None:
        resolve_dist = self._get_package_resolver_dist_settings(pkg)
        return self._return_value_or_default(
            resolve_dist.get("sdist_server_url"), default
        )

    def resolver_include_wheels(
        self, pkg: str, default: bool | None = None
    ) -> bool | None:
        resolve_dist = self._get_package_resolver_dist_settings(pkg)
        return self._return_value_or_default(
            resolve_dist.get("include_wheels"), default
        )

    def resolver_include_sdists(
        self, pkg: str, default: bool | None = None
    ) -> bool | None:
        resolve_dist = self._get_package_resolver_dist_settings(pkg)
        return self._return_value_or_default(
            resolve_dist.get("include_sdists"), default
        )

    def get_package_settings(self, pkg: str) -> dict[str, dict[str, str]]:
        p = self.packages()
        return self._return_value_or_default(
            p.get(overrides.pkgname_to_override_module(pkg)), {}
        )

    def _get_package_download_source_settings(self, pkg: str) -> dict[str, str]:
        p = self.get_package_settings(pkg)
        return self._return_value_or_default(p.get("download_source"), {})

    def _get_package_resolver_dist_settings(self, pkg: str) -> dict[str, str]:
        p = self.get_package_settings(pkg)
        return self._return_value_or_default(p.get("resolver_dist"), {})

    def _return_value_or_default(self, value, default):
        # can't use the "or" method since certain values can be false. Need to explicitly check for None
        return value if value is not None else default


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
