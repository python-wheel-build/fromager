import logging
import pathlib
import typing

import click
import yaml
from packaging.utils import NormalizedName, canonicalize_name

from fromager import clickext, context, overrides, packagesettings

logger = logging.getLogger(__name__)

PkgEnv = dict[NormalizedName, packagesettings.EnvVars]
VariantPkgEnv = dict[
    NormalizedName, dict[packagesettings.Variant, packagesettings.EnvVars]
]
PrebuiltMap = dict[NormalizedName, set[packagesettings.Variant]]


def _parse_envfile(envfile: pathlib.Path) -> packagesettings.EnvVars:
    """Parse a pkg.env file from Fromager 0.27"""
    env: packagesettings.EnvVars = {}
    with envfile.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            key = packagesettings.EnvKey(key.strip())
            value = value.strip()
            if value[0] == value[-1] and (value[0] == '"' or value[0] == "'"):
                value = value[1:-1]
            env[key] = value
    return env


def _load_envfiles(envs_dir: pathlib.Path) -> tuple[PkgEnv, VariantPkgEnv]:
    """Load default and variant env files from Fromager 0.27"""
    default_env: PkgEnv = {}
    for filename in envs_dir.glob("*.env"):
        pkg = canonicalize_name(filename.stem)
        default_env[pkg] = _parse_envfile(filename)

    variants_env: VariantPkgEnv = {}
    for filename in envs_dir.glob("*/*.env"):
        variant = packagesettings.Variant(filename.parent.name)
        pkg = canonicalize_name(filename.stem)

        variants_env.setdefault(pkg, {})[variant] = _parse_envfile(filename)

    return default_env, variants_env


def _migrate_package_envfiles(
    envs_dir: pathlib.Path,
    settings_file: pathlib.Path,
    output_dir: pathlib.Path,
) -> None:
    """Migrate settings.yaml of Fromager 0.27 and earlier

    - "packages" section in setting.yaml
    - "pre_built" section in settings.yaml
    - separate env files in `env_dir` (<name>.yaml, <variant>/<name>.yaml)
    """
    with settings_file.open(encoding="utf-8") as f:
        settings_data: dict[str, typing.Any] = yaml.safe_load(f)

    settings_pkgs: dict[NormalizedName, typing.Any] = {
        canonicalize_name(name): value
        for name, value in settings_data.get("packages", {}).items()
    }

    pre_built: PrebuiltMap = {}
    for variantname, entries in settings_data.get("pre_built", {}).items():
        if not entries:
            continue
        variant = packagesettings.Variant(variantname)
        for pkgname in entries:
            name = NormalizedName(pkgname)
            pre_built.setdefault(name, set()).add(variant)

    default_env, variants_env = _load_envfiles(envs_dir)

    # packages with configuration, pre_built setting, or env files
    pkg_names: set[NormalizedName] = set()
    pkg_names.update(canonicalize_name(pkg) for pkg in settings_pkgs)
    pkg_names.update(default_env)
    pkg_names.update(variants_env)
    pkg_names.update(pre_built)

    package_settings = []
    for name in sorted(pkg_names):
        values: dict[str, typing.Any] = {"variants": {}}
        if name in settings_pkgs:
            values.update(settings_pkgs[name])
        if name in default_env:
            values["env"] = default_env[name]
        if name in variants_env:
            for variant, envvars in variants_env[name].items():
                values["variants"][variant] = {"env": envvars}
        if name in pre_built:
            for variant in pre_built[name]:
                values["variants"].setdefault(variant, {})["pre_built"] = True
        ps = packagesettings.PackageSettings.from_mapping(
            name, values, source=None, has_config=True
        )
        package_settings.append(ps)

    output_dir.mkdir(exist_ok=True)
    for ps in package_settings:
        dump = ps.serialize()
        override_name = overrides.pkgname_to_override_module(ps.name)
        filename = output_dir / f"{override_name}.yaml"
        logger.info("Creating config file %s", filename)
        filename.write_text(yaml.dump(dump), encoding="utf-8")


@click.command()
# --envs-dir will be removed from fromager base command
@click.option(
    "--envs-dir",
    type=clickext.ClickPath(),
    help="location of old environment override files",
    required=True,
)
@click.option(
    "--settings-file",
    type=clickext.ClickPath(),
    help="location of the old application settings file",
    required=True,
)
@click.option(
    "--output-dir",
    type=clickext.ClickPath(),
    help="location to write per-package settings",
    required=True,
)
@click.pass_obj
def migrate_config(
    wkctx: context.WorkContext,
    envs_dir: pathlib.Path,
    settings_file: pathlib.Path,
    output_dir: pathlib.Path,
) -> None:
    """Migrate Fromager 0.27 config to new format"""
    _migrate_package_envfiles(
        envs_dir=envs_dir,
        settings_file=settings_file,
        output_dir=output_dir,
    )
