import logging
import pathlib
import typing

from packaging.requirements import Requirement
from packaging.version import Version

from fromager import build_environment, context, external_commands

logger = logging.getLogger(__name__)


def build_wheel(
    ctx: context.WorkContext,
    build_env: build_environment.BuildEnvironment,
    extra_environ: dict[str, str],
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    version: Version,
) -> None:
    # flit_core is a basic build system dependency for several
    # packages. It is capable of building its own wheels, so we use the
    # bootstrapping instructions to do that and put the wheel in the
    # local server directory for reuse when building other packages via
    # 'pip wheel'.
    #
    # https://flit.pypa.io/en/stable/bootstrap.html
    logger.info('using override to build flit_core wheel in %s', sdist_root_dir)
    external_commands.run(
        [str(build_env.python), '-m', 'flit_core.wheel',
         '--outdir', str(ctx.wheels_build)],
        cwd=str(sdist_root_dir),
        extra_environ=extra_environ,
    )
