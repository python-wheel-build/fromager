import logging
import pathlib
import string
import typing

import yaml
from packaging.requirements import Requirement
from packaging.utils import BuildTag, canonicalize_name
from packaging.version import Version

from . import overrides

logger = logging.getLogger(__name__)


class Settings:
    def __init__(self, data: dict[typing.Any, typing.Any]):
        self._data = data

    def pre_built(self, variant: str) -> set[str]:
        p = self._data.get("pre_built") or {}
        names = p.get(variant) or []
        return set(overrides.pkgname_to_override_module(n) for n in names)

    def packages(self) -> dict[str, dict[str, str]]:
        return self._return_value_or_default(self._data.get("packages"), {})

    def download_source_url(
        self,
        pkg: str,
        req: Requirement | None = None,
        version: Version | str | None = None,
        default: str | None = None,
        resolve_template: bool = True,
    ) -> str | None:
        download_source = self._get_package_download_source_settings(pkg)
        url = self._return_value_or_default(download_source.get("url"), default)
        if url and resolve_template:
            url = _resolve_template(url, req, version)
        return url

    def download_source_destination_filename(
        self,
        pkg: str,
        req: Requirement | None = None,
        version: Version | str | None = None,
        default: str | None = None,
        resolve_template: bool = True,
    ) -> str | None:
        download_source = self._get_package_download_source_settings(pkg)
        destination_filename = self._return_value_or_default(
            download_source.get("destination_filename"), default
        )
        if destination_filename and resolve_template:
            destination_filename = _resolve_template(destination_filename, req, version)
        return destination_filename

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

    def build_dir(self, pkg: str, sdist_root_dir: pathlib.Path) -> pathlib.Path:
        p = self.get_package_settings(pkg)
        if p.get("build_dir"):
            input_build_dir = pathlib.Path(p.get("build_dir"))
            # hack: make path absolute to ensure that any directory escaping is contained
            if ".." in str(input_build_dir):
                raise ValueError(
                    f"{pkg}: build dir {input_build_dir} defined in settings is not relative to sdist root dir"
                )
            # ensure that absolute build_dir path from settings is converted to a relative path
            relative_build_dir = input_build_dir.relative_to(input_build_dir.anchor)
            return sdist_root_dir / relative_build_dir
        return sdist_root_dir

    def build_tag(self, pkg: str, version: Version | str, variant: str) -> BuildTag:
        p = self.get_package_settings(pkg)
        changelog = p.get("changelog", {}).get(str(version), [])
        global_changelog = self._data.get("changelog") or {}
        global_changelog_variant = global_changelog.get(variant) or []
        if not changelog and not global_changelog_variant:
            return ()
        return (len(changelog) + len(global_changelog_variant), "")

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


def _resolve_template(
    template: str | None,
    req: Requirement | None = None,
    version: Version | str | None = None,
):
    if not template:
        return None

    template_env = {}
    if version:
        template_env["version"] = str(version)
    if req:
        template_env["canonicalized_name"] = str(canonicalize_name(req.name))

    try:
        return string.Template(template).substitute(template_env)
    except KeyError:
        if req:
            logger.warning(
                f"{req.name}: Couldn't resolve url or name for {req} using the template: {template_env}"
            )
        else:
            logger.warning(
                f"Couldn't resolve {template} using the template: {template_env}"
            )
        raise


def load(settings_file: pathlib.Path, settings_dir: pathlib.Path) -> Settings:
    settings_data = {}

    filepath = pathlib.Path(settings_file)
    if not filepath.exists():
        logger.debug("settings file %s does not exist, ignoring", filepath.absolute())
    else:
        with open(filepath, "r") as f:
            logger.info("loading settings from %s", filepath.absolute())
            settings_data = yaml.safe_load(f.read())

    # Per-package files are inserted in the `packages` key using the name that
    # will be used to look the value up. Transform any existing keys to that
    # format so we can warn if there are overriding values.
    package_settings_from = {}
    if "packages" not in settings_data:
        settings_data["packages"] = {}
    else:
        new_packages = {}
        for name, value in settings_data["packages"].items():
            package_name = overrides.pkgname_to_override_module(name)
            new_packages[package_name] = value
            package_settings_from[package_name] = settings_file
        settings_data["packages"] = new_packages

    for package_file in sorted(settings_dir.glob("*.yaml")):
        package_name = overrides.pkgname_to_override_module(package_file.stem)
        with open(package_file, "r") as f:
            logger.info(
                "%s: loading settings from %s",
                package_name,
                package_file.absolute(),
            )
            pkg_data = yaml.safe_load(f.read())
            if package_name in settings_data["packages"]:
                logger.warning(
                    "%s: discarding settings from %s",
                    package_name,
                    package_settings_from[package_name],
                )
            settings_data["packages"][package_name] = pkg_data
            package_settings_from[package_name] = package_file

    return Settings(settings_data)
