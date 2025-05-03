from __future__ import annotations

import http.server
import logging
import os
import pathlib
import shutil
import socket
import threading
import typing

if typing.TYPE_CHECKING:
    from . import context

import pypiserver
import pypiserver.bottle
from packaging.utils import parse_wheel_filename

logger = logging.getLogger(__name__)


class LoggingHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: typing.Any) -> None:
        logger.debug(format, *args)


def start_wheel_server(ctx: context.WorkContext) -> None:
    update_wheel_mirror(ctx)
    if ctx.wheel_server_url:
        logger.debug("using external wheel server at %s", ctx.wheel_server_url)
        return
    run_wheel_server(ctx)


def run_wheel_server(
    ctx: context.WorkContext,
    address: str = "localhost",
    port: int = 0,
) -> threading.Thread:
    # bottle does not support port 0, get free high port
    if port == 0:
        with socket.socket() as s:
            s.bind((address, 0))
            port = s.getsockname()[-1]

    ctx.wheel_server_url = f"http://{address}:{port}/simple/"
    logger.info("starting pypiserver at %s", ctx.wheel_server_url)

    app = pypiserver.app(
        roots=[str(ctx.wheels_repo)],
        backend_arg="cached-dir",
        hash_algo=None,
    )
    t = threading.Thread(
        target=pypiserver.bottle.run,
        kwargs={"app": app, "host": address, "port": port, "server": "auto"},
    )
    t.setDaemon(True)
    t.start()
    return t


def update_wheel_mirror(ctx: context.WorkContext) -> None:
    logger.debug("updating wheel mirror")
    for wheel in ctx.wheels_build.glob("*.whl"):
        logger.debug("adding %s", wheel)
        shutil.move(wheel, ctx.wheels_downloads / wheel.name)

    # map wheels to package names
    packages: dict[str, list[pathlib.Path]] = {}
    for wheel in ctx.wheels_downloads.glob("*.whl"):
        name, _, _, _ = parse_wheel_filename(wheel.name)
        package = name.replace("_", "-")
        packages.setdefault(package, []).append(wheel)

    # cleanup stale symlinks
    for wheel in ctx.wheel_server_dir.glob("*/*.whl"):
        if not wheel.is_file():
            logger.debug("removing stale symlink %s", wheel)
            wheel.unlink()

    # symlink wheels
    for package, wheels in packages.items():
        packagedir = ctx.wheel_server_dir / package
        packagedir.mkdir(exist_ok=True, parents=True)
        for wheel in wheels:
            index_wheel = packagedir / wheel.name
            if not index_wheel.is_symlink():
                # relative symlink (Path.relative_to() does not work)
                target = os.path.relpath(wheel, package)
                logger.debug("symlink %s -> %s", index_wheel, target)
                index_wheel.symlink_to(target)
