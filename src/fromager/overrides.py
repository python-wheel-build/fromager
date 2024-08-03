import inspect
import itertools
import logging
import os
import pathlib
import re
import string
import typing
from importlib import metadata

from packaging.utils import NormalizedName, canonicalize_name, parse_sdist_filename
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
) -> None:
    raise RuntimeError(f"failed to load overrides for {ep.name}") from err


def find_and_invoke(
    distname: str,
    method: str,
    default_fn: typing.Callable,
    **kwargs: typing.Any,
) -> typing.Any:
    fn = find_override_method(distname, method)
    if not fn:
        fn = default_fn
    return invoke(fn, **kwargs)


def invoke(fn: typing.Callable, **kwargs: typing.Any) -> typing.Any:
    sig = inspect.signature(fn)
    for arg_name in list(kwargs):
        if arg_name not in sig.parameters:
            logger.warning(
                f"{fn.__module__}.{fn.__name__} override does not take argument {arg_name}"
            )
            kwargs.pop(arg_name)
    return fn(**kwargs)


def _get_dist_info(package_name: str) -> tuple[str, str]:
    dists = metadata.packages_distributions()
    dist_names = dists.get(package_name.split(".")[0])
    if not dist_names:
        return (package_name, "unknown version")
    # package_distributions() returns a mapping of top-level package name to a
    # list of distribution names. The list will only have more than one element
    # if it is a namespace package. For now, assume we do not have that case and
    # take the first element of the list.
    dist_name = dist_names[0]
    dist_version = metadata.version(dist_name)
    return (dist_name, dist_version)


def log_overrides() -> None:
    for ext in _get_extensions():
        dist_name, dist_version = _get_dist_info(ext.module_name)
        logger.debug(
            "loaded override %r: from %s (%s %s)",
            ext.name,
            ext.module_name,
            dist_name,
            dist_version,
        )


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


def get_patch_directories(
    patches_dir: pathlib.Path, source_root_dir: pathlib.Path
) -> list[pathlib.Path]:
    """
    This function will return directories that may contain patches for a specific requirement.
    It takes in patches directory and a source root directory as input.
    The output will be a list of all directories containing patches for that requirement
    """
    # Get the req name as per the source_root_dir naming conventions
    req_name = source_root_dir.name.rsplit("-", 1)[0]
    patches = sorted((patches_dir).glob(f"{req_name}*"))
    filtered_patches = _filter_patches_based_on_req(patches, req_name)
    return filtered_patches


# Helper method to filter the unwanted patches using a regex
def _filter_patches_based_on_req(
    patches: list[pathlib.Path], req_name: str
) -> list[pathlib.Path]:
    # Set up regex to filter out unwanted patches.
    pattern = re.compile(rf"^{req_name}-v?(\d+\.)+\d+")
    filtered_patches = [s for s in patches if pattern.match(s.name)]
    # filtered_patches won't contain patches for current version of req
    return filtered_patches


def extra_environ_for_pkg(
    envs_dir: pathlib.Path,
    pkgname: str,
    variant: str,
) -> dict[str, str]:
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
            "%s: found %s environment settings in %s",
            pkgname,
            variant,
            env_file,
        )
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # remove quotes if they surround the value
                if value[0] == value[-1] and (value[0] == '"' or value[0] == "'"):
                    value = value[1:-1]
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


def find_override_method(distname: str, method: str) -> typing.Callable | None:
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
    return typing.cast(typing.Callable, getattr(mod, method))


def list_all(
    patches_dir: pathlib.Path,
    envs_dir: pathlib.Path,
    settings: dict[str, dict],
    test: bool = False,
) -> list[NormalizedName]:
    exts = _get_extensions()

    def patched_projects() -> typing.Generator[NormalizedName, None, None]:
        for item in patches_dir.glob("*"):
            if not item.is_dir():
                continue
            fake_sdist = item.name + ".tar.gz"
            name, _ = parse_sdist_filename(fake_sdist)
            yield name

    def patched_projects_legacy() -> typing.Generator[NormalizedName, None, None]:
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

    def env_projects() -> typing.Generator[str, None, None]:
        for item in envs_dir.glob("*/*.env"):
            yield item.stem

    def projects_with_predefined_download_source() -> typing.Generator[str, None, None]:
        yield from settings

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
