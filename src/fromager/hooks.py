import logging
import pathlib
import typing

from packaging.requirements import Requirement
from stevedore import extension, hook

from fromager import context

_mgrs: dict[str, hook.HookManager] = {}
logger = logging.getLogger(__name__)


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
        logger.debug(f"{name} hooks: {mgr.names()}")
    return mgr


def _die_on_plugin_load_failure(
    mgr: hook.HookManager,
    ep: extension.Extension,
    err: Exception,
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
        logger.info(f"{req.name}: starting post-build hooks")
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
