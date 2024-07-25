import functools
import http.server
import logging
import os
import shutil
import threading
import typing

from . import context, external_commands

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
    server = http.server.ThreadingHTTPServer(
        (address, port),
        functools.partial(LoggingHTTPRequestHandler, directory=str(ctx.wheels_repo)),
        bind_and_activate=False,
    )
    server.timeout = 0.5
    server.allow_reuse_address = True

    logger.debug(f"address {server.server_address}")
    server.server_bind()
    ctx.wheel_server_url = f"http://{address}:{server.server_port}/simple/"

    logger.debug("starting wheel server at %s", ctx.wheel_server_url)
    server.server_activate()

    def serve_forever(server: http.server.ThreadingHTTPServer) -> None:
        # ensure server.server_close() is called
        with server:
            server.serve_forever()

    t = threading.Thread(target=serve_forever, args=(server,))
    t.setDaemon(True)
    t.start()
    return t


def update_wheel_mirror(ctx: context.WorkContext) -> None:
    logger.debug("updating wheel mirror")
    for wheel in ctx.wheels_build.glob("*.whl"):
        logger.debug("adding %s", wheel)
        shutil.move(wheel, ctx.wheels_downloads / wheel.name)
    external_commands.run(
        [
            "pypi-mirror",
            "create",
            "-d",
            os.fspath(ctx.wheels_downloads),
            "-m",
            os.fspath(ctx.wheel_server_dir),
        ]
    )
