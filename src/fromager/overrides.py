from __future__ import annotations

import importlib
import inspect
import logging
import pathlib
import typing
from importlib import metadata

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
from stevedore import extension

if typing.TYPE_CHECKING:
    from . import build_environment, context
    from .requirements_file import RequirementType
    from .resolver import BaseProvider

# An interface for reretrieving per-package information which influences
# the build process for a particular package - i.e. for a given package
# and build target, what patches should we apply, what environment variables
# should we set, etc.
logger = logging.getLogger(__name__)


_mgr: extension.ExtensionManager | None = None


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
    ep: metadata.EntryPoint,
    err: BaseException,
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
) -> typing.Iterator[pathlib.Path]:
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


_F = typing.TypeVar("_F", bound=typing.Callable[..., typing.Any])


def _default_hook(module: str, func: str) -> typing.Callable[[_F], _F]:
    """Decorator that annotates a Protocol method with its default implementation.

    Stores a ``fromager_default`` attribute as a ``(module, func)`` tuple
    on the decorated function so the mapping from hook name to default can
    be discovered at runtime.
    """

    def decorator(fn: _F) -> _F:
        fn.fromager_default = (module, func)  # type: ignore[attr-defined]
        return fn

    return decorator


class OverrideHookProtocol(typing.Protocol):
    """Protocol defining the interface for per-package override hooks.

    Override modules may implement any subset of these methods to customize
    the build process for a specific package. See the default implementations
    for each hook's behavior when no override is provided.
    """

    @classmethod
    def list_hooks(cls) -> list[str]:
        """Return a list of hook names defined on this Protocol."""
        return [
            name for name, obj in vars(cls).items() if hasattr(obj, "fromager_default")
        ]

    @classmethod
    def get_default(cls, hook_name: str) -> typing.Callable[..., typing.Any]:
        """Return the default function object for a hook name."""
        obj = getattr(cls, hook_name, None)
        if obj is None or not hasattr(obj, "fromager_default"):
            raise KeyError(hook_name)
        module_name, func_name = obj.fromager_default
        module = importlib.import_module(module_name)
        return typing.cast(typing.Callable[..., typing.Any], getattr(module, func_name))

    @classmethod
    def check_signature(
        cls,
        func: typing.Callable[..., typing.Any],
        *,
        hook_name: str | None = None,
    ) -> None:
        """Check that a function's argument names match the protocol method.

        Only argument names are compared; the check ignores whether arguments
        are positional or keyword-only because all hooks are called with
        keyword arguments.
        """
        if hook_name is None:
            hook_name = func.__name__
        proto_method = getattr(cls, hook_name, None)
        if proto_method is None or not hasattr(proto_method, "fromager_default"):
            raise KeyError(hook_name)
        proto_spec = inspect.getfullargspec(proto_method)
        # Skip 'self' (first parameter of a protocol method)
        expected_args = set(proto_spec.args[1:] + proto_spec.kwonlyargs)
        func_spec = inspect.getfullargspec(func)
        func_args = set(func_spec.args + func_spec.kwonlyargs)
        if expected_args != func_args:
            raise TypeError(
                f"{hook_name}: argument names mismatch: "
                f"expected {sorted(expected_args)}, got {sorted(func_args)}"
            )

    @_default_hook("fromager.wheels", "default_add_extra_metadata_to_wheels")
    def add_extra_metadata_to_wheels(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        extra_environ: dict[str, str],
        sdist_root_dir: pathlib.Path,
        dist_info_dir: pathlib.Path,
    ) -> dict[str, typing.Any]:
        """Add extra metadata files to built wheels.

        Default: :func:`fromager.wheels.default_add_extra_metadata_to_wheels`
        """

    @_default_hook("fromager.sources", "default_build_sdist")
    def build_sdist(
        self,
        ctx: context.WorkContext,
        extra_environ: dict,
        req: Requirement,
        version: Version,
        sdist_root_dir: pathlib.Path,
        build_env: build_environment.BuildEnvironment,
        build_dir: pathlib.Path,
    ) -> pathlib.Path:
        """Build an sdist from the prepared source tree.

        Default: :func:`fromager.sources.default_build_sdist`
        """

    @_default_hook("fromager.wheels", "default_build_wheel")
    def build_wheel(
        self,
        ctx: context.WorkContext,
        build_env: build_environment.BuildEnvironment,
        extra_environ: dict[str, str],
        req: Requirement,
        sdist_root_dir: pathlib.Path,
        version: Version,
        build_dir: pathlib.Path,
    ) -> pathlib.Path:
        """Build a wheel from the prepared source tree.

        Default: :func:`fromager.wheels.default_build_wheel`
        """

    @_default_hook("fromager.sources", "default_download_source")
    def download_source(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
        sdists_downloads_dir: pathlib.Path,
    ) -> pathlib.Path:
        """Download the source archive for a requirement.

        Default: :func:`fromager.sources.default_download_source`
        """

    @_default_hook("fromager.finders", "default_expected_source_archive_name")
    def expected_source_archive_name(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        dist_version: str,
    ) -> str | None:
        """Return the expected filename for a source archive.

        Default: :func:`fromager.finders.default_expected_source_archive_name`
        """

    @_default_hook("fromager.finders", "default_expected_source_directory_name")
    def expected_source_directory_name(
        self,
        req: Requirement,
        dist_version: str,
    ) -> str:
        """Return the expected directory name after unpacking a source archive.

        Default: :func:`fromager.finders.default_expected_source_directory_name`
        """

    @_default_hook("fromager.dependencies", "default_get_build_backend_dependencies")
    def get_build_backend_dependencies(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        sdist_root_dir: pathlib.Path,
        build_dir: pathlib.Path,
        extra_environ: dict[str, str],
        build_env: build_environment.BuildEnvironment,
    ) -> typing.Iterable[str]:
        """Get build backend dependencies (PEP 517 get_requires_for_build_wheel).

        Default: :func:`fromager.dependencies.default_get_build_backend_dependencies`
        """

    @_default_hook("fromager.dependencies", "default_get_build_sdist_dependencies")
    def get_build_sdist_dependencies(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        sdist_root_dir: pathlib.Path,
        build_dir: pathlib.Path,
        extra_environ: dict[str, str],
        build_env: build_environment.BuildEnvironment,
    ) -> typing.Iterable[str]:
        """Get build sdist dependencies.

        Default: :func:`fromager.dependencies.default_get_build_sdist_dependencies`
        """

    @_default_hook("fromager.dependencies", "default_get_build_system_dependencies")
    def get_build_system_dependencies(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        sdist_root_dir: pathlib.Path,
        build_dir: pathlib.Path,
    ) -> typing.Iterable[str]:
        """Get build system dependencies from pyproject.toml [build-system] requires.

        Default: :func:`fromager.dependencies.default_get_build_system_dependencies`
        """

    @_default_hook("fromager.dependencies", "default_get_install_dependencies_of_sdist")
    def get_install_dependencies_of_sdist(
        self,
        *,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        sdist_root_dir: pathlib.Path,
        build_env: build_environment.BuildEnvironment,
        extra_environ: dict[str, str],
        build_dir: pathlib.Path,
        config_settings: dict[str, str],
    ) -> set[Requirement]:
        """Get install dependencies (Requires-Dist) from source distribution.

        Default: :func:`fromager.dependencies.default_get_install_dependencies_of_sdist`
        """

    @_default_hook("fromager.resolver", "default_resolver_provider")
    def get_resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        sdist_server_url: str,
        include_sdists: bool,
        include_wheels: bool,
        req_type: RequirementType | None = None,
        ignore_platform: bool = False,
    ) -> BaseProvider:
        """Return a resolver provider for resolving package versions.

        Default: :func:`fromager.resolver.default_resolver_provider`
        """

    @_default_hook("fromager.sources", "default_prepare_source")
    def prepare_source(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        source_filename: pathlib.Path,
        version: Version,
    ) -> tuple[pathlib.Path, bool]:
        """Unpack, modify, and prepare source for building.

        Default: :func:`fromager.sources.default_prepare_source`
        """

    @_default_hook("fromager.packagesettings", "default_update_extra_environ")
    def update_extra_environ(
        self,
        *,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version | None,
        sdist_root_dir: pathlib.Path,
        extra_environ: dict[str, str],
        build_env: build_environment.BuildEnvironment,
    ) -> None:
        """Update extra_environ dict in-place with additional environment variables.

        Default: :func:`fromager.packagesettings.default_update_extra_environ`
        """
