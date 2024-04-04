import logging

from . import external_commands, overrides, server

logger = logging.getLogger(__name__)


def build_wheel(ctx, req_type, req, resolved_name, why, sdist_root_dir):
    logger.info('building wheel for %s', resolved_name)
    builder = overrides.find_override_method(req.name, 'build_wheel')
    if not builder:
        builder = _default_build_wheel
    wheel_filenames = builder(ctx, req_type, req, resolved_name, why, sdist_root_dir)
    for wheel in wheel_filenames:
        server.add_wheel_to_mirror(ctx, sdist_root_dir.name, wheel)
    ctx.add_to_build_order(req_type, req, resolved_name, why)
    logger.info('built wheel for %s', resolved_name)


def _default_build_wheel(ctx, req_type, req, resolved_name, why, sdist_root_dir):
    cmd = [
        'firejail',
        '--net=none',
        '--join=local-wheel-server',
        'pip', '-vvv',
        '--disable-pip-version-check',
        'wheel',
        '--no-cache-dir',
        '--index-url', 'http://127.0.0.1:8000/simple/',
        '--only-binary', ':all:',
        '--wheel-dir', sdist_root_dir.parent.absolute(),
        '--no-deps',
        '.',
    ]
    external_commands.run(cmd, cwd=sdist_root_dir)
    return sdist_root_dir.parent.glob('*.whl')
