from __future__ import annotations

import logging
import pathlib
import typing
from importlib.metadata import EntryPoint

from packaging.requirements import Requirement
from stevedore import extension, hook

from . import overrides
from .threading_utils import with_thread_lock

if typing.TYPE_CHECKING:
    from . import context

_mgrs: dict[str, hook.HookManager] = {}

logger = logging.getLogger(__name__)


@with_thread_lock()
def _get_hooks(name: str) -> hook.HookManager:
    mgr = _mgrs.get(name)
    if mgr is None:
        logger.debug(f"loading hooks for {name}")
        mgr = hook.HookManager(
            namespace="fromager.hooks",
            name=name,
            invoke_on_load=False,
            on_load_failure_callback=_die_on_plugin_load_failure,
        )
        _mgrs[name] = mgr
        logger.debug(f"{name} hooks: {mgr.names()}, {mgr.list_entry_points()}")
    if not mgr.names():
        logger.debug(f"hook {name} has no entry points")
    return mgr


def log_hooks() -> None:
    # We load the hooks differently here because we want all of them when
    # normally we would load them by name.
    _mgr: extension.ExtensionManager = extension.ExtensionManager(
        namespace="fromager.hooks",
        invoke_on_load=False,
        on_load_failure_callback=_die_on_plugin_load_failure,
    )
    for ext in _mgr:
        dist_name, dist_version = overrides._get_dist_info(ext.module_name)
        logger.debug(
            "loaded hook %r: from %s (%s %s)",
            ext.name,
            ext.module_name,
            dist_name,
            dist_version,
        )


def _die_on_plugin_load_failure(
    mgr: extension.ExtensionManager,
    ep: EntryPoint,
    err: BaseException,
) -> typing.NoReturn:
    raise RuntimeError(f"failed to load overrides for {ep.name}") from err


def run_post_build_hooks(
    ctx: context.WorkContext,
    req: Requirement,
    dist_name: str,
    dist_version: str,
    sdist_filename: pathlib.Path,
    wheel_filename: pathlib.Path,
) -> None:
    hook_mgr = _get_hooks("post_build")
    if hook_mgr.names():
        logger.info(
            f"starting post_build hooks for {dist_name}=={dist_version}, "
            f"sdist: {sdist_filename}, wheel_filename: {wheel_filename}"
        )
    for ext in hook_mgr:
        # NOTE: Each hook is responsible for doing its own logging for
        # start/stop because we don't have a good name to use here.
        ext.plugin(
            ctx=ctx,
            req=req,
            dist_name=dist_name,
            dist_version=dist_version,
            sdist_filename=sdist_filename,
            wheel_filename=wheel_filename,
        )


def run_post_bootstrap_hooks(
    ctx: context.WorkContext,
    req: Requirement,
    dist_name: str,
    dist_version: str,
    sdist_filename: pathlib.Path | None,
    wheel_filename: pathlib.Path | None,
) -> None:
    hook_mgr = _get_hooks("post_bootstrap")
    if hook_mgr.names():
        logger.info(
            f"starting post_bootstrap hooks for {dist_name}=={dist_version}, "
            f"sdist: {sdist_filename}, wheel_filename: {wheel_filename}"
        )
    for ext in hook_mgr:
        # NOTE: Each hook is responsible for doing its own logging for
        # start/stop because we don't have a good name to use here.
        ext.plugin(
            ctx=ctx,
            req=req,
            dist_name=dist_name,
            dist_version=dist_version,
            sdist_filename=sdist_filename,
            wheel_filename=wheel_filename,
        )


def run_prebuilt_wheel_hooks(
    ctx: context.WorkContext,
    req: Requirement,
    dist_name: str,
    dist_version: str,
    wheel_filename: pathlib.Path,
) -> None:
    hook_mgr = _get_hooks("prebuilt_wheel")
    if hook_mgr.names():
        logger.info(
            f"starting prebuilt_wheel hooks for {dist_name}=={dist_version}, "
            f"wheel_filename: {wheel_filename}"
        )
    for ext in hook_mgr:
        ext.plugin(
            ctx=ctx,
            req=req,
            dist_name=dist_name,
            dist_version=dist_version,
            wheel_filename=wheel_filename,
        )
