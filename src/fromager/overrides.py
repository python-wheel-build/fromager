import itertools
import logging
import pathlib
import typing

from packaging.utils import canonicalize_name
from stevedore import extension

# An interface for reretrieving per-package information which influences
# the build process for a particular package - i.e. for a given package
# and build target, what patches should we apply, what environment variables
# should we set, etc.


logger = logging.getLogger(__name__)


_mgr = None


def _get_extensions() -> extension.ExtensionManager:
    global _mgr
    if _mgr is None:
        _mgr = extension.ExtensionManager(
            namespace="fromager.project_overrides",
            invoke_on_load=False,
            on_load_failure_callback=_die_on_plugin_load_failure,
        )
    return _mgr


def _die_on_plugin_load_failure(
    mgr: extension.ExtensionManager,
    ep: extension.Extension,
    err: Exception,
):
    raise RuntimeError(f"failed to load overrides for {ep.name}") from err


def log_overrides():
    logger.debug("loaded overrides for %s", _get_extensions().entry_points_names())


def patches_for_source_dir(
    patches_dir: pathlib.Path, source_dir_name: str
) -> typing.Iterable[pathlib.Path]:
    """Iterator producing patches to apply to the source dir.

    Input should be the base directory name, not a full path.

    Yields pathlib.Path() references to patches in the order they
    should be applied, which is controlled through lexical sorting of
    the filenames.

    """
    return itertools.chain(
        sorted(patches_dir.glob(source_dir_name + "*.patch")),  # legacy format
        sorted((patches_dir / source_dir_name).glob("*.patch")),  # safer
    )


def extra_environ_for_pkg(
    envs_dir: pathlib.Path,
    pkgname: str,
    variant: str,
) -> dict:
    """Return a dict of extra environment variables for a particular package.

    Extra environment variables are stored in per-package .env files in the
    envs package, with a key=value per line.
    """
    extra_environ = {}

    pkgname = pkgname_to_override_module(pkgname)
    variant_dir = envs_dir / variant
    env_file = variant_dir / (pkgname + ".env")

    if env_file.exists():
        logger.debug(
            "found %s environment settings for %s in %s", variant, pkgname, env_file
        )
        with open(env_file, "r") as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                extra_environ[key.strip()] = value.strip()
    return extra_environ


def pkgname_to_override_module(pkgname: str) -> str:
    canonical_name = canonicalize_name(pkgname)
    module_name = canonical_name.replace("-", "_")
    return module_name


def find_override_method(distname: str, method: str) -> typing.Callable:
    """Given a distname and method name, look for an override implementation of the method.

    If there is no module or no method, return None.

    If the module exists and cannot be imported, propagate the exception.
    """
    distname = pkgname_to_override_module(distname)
    try:
        mod = _get_extensions()[distname].plugin
    except KeyError:
        logger.debug(
            "no override module for %s among %s",
            distname,
            _get_extensions().entry_points_names(),
        )
        return None
    if not hasattr(mod, method):
        logger.debug("no %s override for %s", method, distname)
        return None
    logger.info("found %s override for %s", method, distname)
    return getattr(mod, method)
