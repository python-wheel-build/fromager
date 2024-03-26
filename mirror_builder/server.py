import functools
import http.server
import logging
import shutil
import subprocess
import threading

logger = logging.getLogger(__name__)


def add_wheel_to_mirror(ctx, name_version, filename):
    logger.info('copying wheel %s to mirror', filename)
    shutil.copyfile(filename, ctx.wheels_downloads / filename.name)
    update_wheel_mirror(ctx)
    ctx.mark_as_seen(name_version)


def start_wheel_server(ctx):
    update_wheel_mirror(ctx)
    logger.debug('wheel port %s', ctx.wheel_server_port)
    server = http.server.ThreadingHTTPServer(
        ('localhost', ctx.wheel_server_port),
        functools.partial(http.server.SimpleHTTPRequestHandler, directory=ctx.wheels_repo),
        bind_and_activate=False,
    )
    server.timeout = 0.5
    server.allow_reuse_address = True

    logger.debug(f'address {server.server_address}')
    server.server_bind()
    ctx.wheel_server_port = server.server_port # in case a port was allocated for us

    logger.debug('starting wheel server at %s', ctx.wheel_server_url)
    server.server_activate()

    def serve_forever(server):
        # ensure server.server_close() is called
        with server:
            server.serve_forever()
    t = threading.Thread(target=serve_forever, args=(server,))
    t.setDaemon(True)
    t.start()


def update_wheel_mirror(ctx):
    logger.debug('updating wheel mirror')
    subprocess.check_call([
        'pypi-mirror',
        'create',
        '-d', ctx.wheels_downloads,
        '-m', ctx.wheel_server_dir,
    ])
