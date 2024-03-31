import logging
import subprocess

from . import sdist, server

logger = logging.getLogger(__name__)


def bootstrap_build_dependencies(ctx):
    # flit_core is a basic build system dependency for several
    # packages. It is capable of building its own wheels, so we use the
    # bootstrapping instructions to do that and put the wheel in the
    # local server directory for reuse when building other packages via
    # 'pip wheel'.
    #
    # https://flit.pypa.io/en/stable/bootstrap.html
    sdist_filename = sdist.download_sdist(ctx, ['flit_core'])
    resolved_name = sdist.get_resolved_name(sdist_filename)
    sdist_root_dir = sdist.unpack_sdist(ctx, sdist_filename)
    logger.info('building flit_core wheel in %s', sdist_root_dir)
    subprocess.check_call(
        ['python3', '-m', 'flit_core.wheel'],
        cwd=sdist_root_dir,
    )
    for name in (sdist_root_dir / 'dist').glob('*.whl'):
        server.add_wheel_to_mirror(ctx, sdist_root_dir.name, name)
    ctx.add_to_build_order('build-system', 'flit_core', resolved_name, '')
