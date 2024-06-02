import logging

from fromager import external_commands

logger = logging.getLogger(__name__)


def build_wheel(ctx, build_env, extra_environ, req, sdist_root_dir):
    # flit_core is a basic build system dependency for several
    # packages. It is capable of building its own wheels, so we use the
    # bootstrapping instructions to do that and put the wheel in the
    # local server directory for reuse when building other packages via
    # 'pip wheel'.
    #
    # https://flit.pypa.io/en/stable/bootstrap.html
    logger.info('using override to build flit_core wheel in %s', sdist_root_dir)
    external_commands.run(
        [build_env.python, '-m', 'flit_core.wheel',
         '--outdir', ctx.wheels_build],
        cwd=sdist_root_dir,
        extra_environ=extra_environ,
    )
