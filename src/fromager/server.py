from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import shutil
import socket
import stat
import textwrap
import threading
import typing
from urllib.parse import quote

import uvicorn
from packaging.utils import parse_wheel_filename
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from .threading_utils import with_thread_lock

if typing.TYPE_CHECKING:
    from . import context

logger = logging.getLogger(__name__)


def start_wheel_server(ctx: context.WorkContext) -> None:
    update_wheel_mirror(ctx)
    if ctx.wheel_server_url:
        logger.debug("using external wheel server at %s", ctx.wheel_server_url)
        return
    run_wheel_server(ctx)


def run_wheel_server(
    ctx: context.WorkContext,
    address: str = "127.0.0.1",
    port: int = 0,
) -> tuple[uvicorn.Server, socket.socket, threading.Thread]:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()

    app = make_app(ctx.wheel_server_dir)
    server, sock, thread = _run_background_thread(
        loop=loop, app=app, host=address, port=port
    )

    realport = sock.getsockname()[1]
    ctx.wheel_server_url = f"http://{address}:{realport}/simple/"

    logger.info("started wheel server at %s", ctx.wheel_server_url)
    return server, sock, thread


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


class SimpleHTMLIndex:
    """Simple HTML Repository API (1.0)

    https://packaging.python.org/en/latest/specifications/simple-repository-api/
    """

    html_index = textwrap.dedent(
        """\
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta name="pypi:repository-version" content="1.0">
            <title>Simple index</title>
        </head>
        <body>
        {entries}
        </body>
        </html>
        """
    )

    html_project = textwrap.dedent(
        """\
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta name="pypi:repository-version" content="1.0">
            <title>Links for {project}</title>
        </head>
        <body>
            <h1>Links for {project}</h1>
        {entries}
        </body>
        </html>
        """
    )

    def __init__(self, basedir: pathlib.Path) -> None:
        self.basedir = basedir.resolve()

    def _as_anchor(self, prefix: str, direntry: os.DirEntry) -> str:
        quoted = quote(direntry.name)
        return f'<a href="{prefix}/{quoted}">{quoted}</a><br/>'

    async def root(self, request: Request) -> Response:
        return RedirectResponse(url="/simple")

    async def index_page(self, request: Request) -> Response:
        prefix = "/simple"
        try:
            dirs = [
                self._as_anchor(prefix, direntry)
                for direntry in os.scandir(self.basedir)
                if direntry.is_dir(follow_symlinks=False)
            ]
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"'{self.basedir}' missing"
            ) from None

        content = self.html_index.format(entries="\n".join(dirs))
        return HTMLResponse(content=content)

    async def project_page(self, request: Request) -> Response:
        project = request.path_params["project"]
        project_dir = self.basedir / project
        prefix = f"/simple/{project}"
        try:
            dirs = [
                self._as_anchor(prefix, direntry)
                for direntry in os.scandir(project_dir)
                if direntry.name.endswith((".whl", ".whl.metadata", ".tar.gz"))
                and direntry.is_file(follow_symlinks=True)
            ]
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"'{project_dir}' missing"
            ) from None
        content = self.html_project.format(
            project=quote(project), entries="\n".join(dirs)
        )
        return HTMLResponse(content=content)

    async def server_file(self, request: Request) -> Response:
        project = request.path_params["project"]
        filename = request.path_params["filename"]

        path: pathlib.Path = self.basedir / project / filename
        try:
            stat_result = path.stat(follow_symlinks=True)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found") from None
        if not stat.S_ISREG(stat_result.st_mode):
            raise HTTPException(status_code=400, detail="Not a regular file")

        if filename.endswith(".tar.gz"):
            media_type = "application/x-tar"
        elif filename.endswith(".whl"):
            media_type = "application/zip"
        elif filename.endswith(".whl.metadata"):
            media_type = "binary/octet-stream"
        else:
            raise HTTPException(status_code=400, detail="Bad request")

        return FileResponse(path, media_type=media_type, stat_result=stat_result)


def make_app(basedir: pathlib.Path) -> Starlette:
    """Create a Starlette app with routing"""
    si = SimpleHTMLIndex(basedir)
    routes: list[Route] = [
        Route("/", endpoint=si.root),
        Route("/simple", endpoint=si.index_page),
        Route("/simple/{project:str}", endpoint=si.project_page),
        Route("/simple/{project:str}/{filename:str}", endpoint=si.server_file),
    ]
    return Starlette(routes=routes)


def _run_background_thread(
    loop: asyncio.AbstractEventLoop,
    app: Starlette,
    host="127.0.0.1",
    port=0,
    **kwargs,
) -> tuple[uvicorn.Server, socket.socket, threading.Thread]:
    """Run uvicorn server in a daemon thread"""
    config = uvicorn.Config(app=app, host=host, port=port, **kwargs)
    server = uvicorn.Server(config=config)
    sock = server.config.bind_socket()

    def _run_background() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve(sockets=[sock]))

    thread = threading.Thread(target=_run_background, args=(), daemon=True)
    thread.start()
    return server, sock, thread


def stop_server(server: uvicorn.Server, loop: asyncio.AbstractEventLoop) -> None:
    """Stop server, blocks until server is shut down"""
    fut = asyncio.run_coroutine_threadsafe(server.shutdown(), loop=loop)
    fut.result()
