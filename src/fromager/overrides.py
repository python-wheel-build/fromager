import inspect
import itertools
import logging
import os
import pathlib
import string
import typing

from packaging.utils import canonicalize_name, parse_sdist_filename
from packaging.version import Version
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


def find_and_invoke(distname: str, method: str, default_fn: typing.Callable, **kwargs):
    fn = find_override_method(distname, method)
    if not fn:
        fn = default_fn
    return invoke(fn, **kwargs)


def invoke(fn: typing.Callable, **kwargs):
    sig = inspect.signature(fn)
    for arg_name in list(kwargs):
        if arg_name not in sig.parameters:
            logger.warning(
                f"{fn.__module__}.{fn.__name__} override does not take argument {arg_name}"
            )
            kwargs.pop(arg_name)
    return fn(**kwargs)


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
    return sorted((patches_dir / source_dir_name).glob("*.patch"))


def extra_environ_for_pkg(
    envs_dir: pathlib.Path,
    pkgname: str,
    variant: str,
) -> dict:
    """Return a dict of extra environment variables for a particular package.

    Extra environment variables are stored in per-package .env files in the
    envs package, with a key=value per line.

    Supports $NAME and ${NAME} substition from process environment and
    previous keys in an env file. Raises 'KeyError' for unknown keys and
    'ValueError' for subshell "$()" expressions.
    """
    extra_environ = {}
    template_env = os.environ.copy()

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
                key = key.strip()
                value = value.strip()
                if "$(" in value:
                    raise ValueError(f"'{value}': subshell '$()' is not supported.")
                value = string.Template(value).substitute(template_env)
                extra_environ[key] = value
                # subsequent key-value pairs can depend on previously vars.
                template_env[key] = value
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
            "%s: no override module among %s",
            distname,
            _get_extensions().entry_points_names(),
        )
        return None
    if not hasattr(mod, method):
        logger.debug("%s: no %s override", distname, method)
        return None
    logger.info("%s: found %s override", distname, method)
    return getattr(mod, method)


def list_all(
    patches_dir: pathlib.Path,
    envs_dir: pathlib.Path,
    download_source: dict[str, dict[str, str]],
    test: bool = False,
):
    exts = _get_extensions()

    def patched_projects():
        for item in patches_dir.glob("*"):
            if not item.is_dir():
                continue
            fake_sdist = item.name + ".tar.gz"
            name, _ = parse_sdist_filename(fake_sdist)
            yield name

    def patched_projects_legacy():
        for item in patches_dir.glob("*.patch"):
            parts = []
            for p in item.stem.split("-"):
                parts.append(p)
                try:
                    Version(p)
                    # Stop when we get something we can parse as a version string.
                    break
                except Exception:
                    pass
            fake_sdist = ("-".join(parts)) + ".tar.gz"
            try:
                name, _ = parse_sdist_filename(fake_sdist)
            except Exception as err:
                logger.warning(f"could not extract package name from {item}: {err}")
                continue
            yield name

    def env_projects():
        for item in envs_dir.glob("*/*.env"):
            yield item.stem

    def projects_with_predefined_download_source():
        yield from download_source

    # Use canonicalize_name() to ensure we can correctly remove duplicate
    # entries from the return list.
    return sorted(
        set(
            canonicalize_name(n)
            for n in itertools.chain(
                exts.names(),
                patched_projects(),
                patched_projects_legacy(),
                env_projects(),
                projects_with_predefined_download_source(),
            )
            if not test
            or n != "fromager_test"  # filter out test package except in test mode
        )
    )
