from __future__ import annotations

import functools
import http.server
import io
import logging
import os
import pathlib
import shutil
import threading
import typing

from packaging.utils import parse_wheel_filename

from .threading_utils import with_thread_lock

if typing.TYPE_CHECKING:
    from . import context

logger = logging.getLogger(__name__)


class LoggingHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: typing.Any) -> None:
        logger.debug(format, *args)

    def list_directory(self, path: str | os.PathLike[str]) -> io.BytesIO | None:
        # default list_directory() function appends an "@" to every symbolic
        # link. pypi_simple does not understand the "@". Rewrite the body
        # while keeping the same content length.
        old: io.BytesIO | None = super().list_directory(path)
        if old is None:
            return None
        new = io.BytesIO()
        for oldline in old:
            new.write(oldline.replace(b"@</a>", b"</a> "))
        new.seek(0)
        return new


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


@with_thread_lock()
def update_wheel_mirror(ctx: context.WorkContext) -> None:
    for wheel in ctx.wheels_build.glob("*.whl"):
        logger.info("adding %s to local wheel server", wheel.name)
        downloads_dest_filename = ctx.wheels_downloads / wheel.name
        # Always move the file so the code managing the timer for the
        # wheels does not find more than one wheel in the build
        # directory.
        shutil.move(wheel, downloads_dest_filename)

    wheels: list[pathlib.Path] = []
    wheels.extend(ctx.wheels_downloads.glob("*.whl"))
    wheels.extend(ctx.wheels_prebuilt.glob("*.whl"))

    for wheel in wheels:
        # Now also symlink the files into the simple hierarchy. We always
        # process all files to be safe.
        (normalized_name, _, _, _) = parse_wheel_filename(wheel.name)
        simple_dest_filename = ctx.wheel_server_dir / normalized_name / wheel.name

        if simple_dest_filename.is_symlink() and not simple_dest_filename.is_file():
            logger.debug("remove dangling symlink %s", simple_dest_filename)
            simple_dest_filename.unlink()

        if not simple_dest_filename.is_file():
            relpath = os.path.relpath(wheel, simple_dest_filename.parent)
            logger.debug("linking %s -> %s into local index", wheel.name, relpath)
            simple_dest_filename.parent.mkdir(parents=True, exist_ok=True)
            simple_dest_filename.symlink_to(relpath)
