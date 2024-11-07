import inspect
import logging
import pathlib
import typing
from importlib import metadata

from packaging.requirements import Requirement
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

    result = invoke(fn, **kwargs)
    if fn is default_fn:
        log_method = logger.debug
    else:
        log_method = logger.info
    log_method(f"{distname}: override method {fn.__name__} returned {result}")

    return result


def invoke(fn: typing.Callable, **kwargs: typing.Any) -> typing.Any:
    sig = inspect.signature(fn)
    for arg_name in list(kwargs):
        if arg_name not in sig.parameters:
            logger.warning(
                f"{fn.__module__}.{fn.__name__} override does not take argument {arg_name}"
            )
            kwargs.pop(arg_name)
        logger.debug(f"{fn.__name__} takes argument: {arg_name}")
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


def get_versioned_patch_directories(
    patches_dir: pathlib.Path,
    req: Requirement,
) -> typing.Generator[pathlib.Path, None, None]:
    """
    This function will return directories that may contain patches for any version of a specific requirement.
    """
    # Get the req name as per the source_root_dir naming conventions
    override_name = pkgname_to_override_module(req.name)
    return patches_dir.glob(f"{override_name}-*")


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
