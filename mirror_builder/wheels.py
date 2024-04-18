import logging
import platform
import tempfile
import venv

from . import external_commands, pkgs

logger = logging.getLogger(__name__)


def build_wheel(ctx, req, sdist_root_dir, build_env):
    logger.info('building wheel for %s in %s writing to %s', req.name, sdist_root_dir,
                ctx.wheels_build)
    builder = pkgs.find_override_method(req.name, 'build_wheel')
    if not builder:
        builder = _default_build_wheel
    extra_environ = pkgs.extra_environ_for_pkg(req.name)
    builder(ctx, build_env, extra_environ, req, sdist_root_dir)
    wheels = list(ctx.wheels_build.glob('*.whl'))
    if wheels:
        return wheels[0]
    return None


def _default_build_wheel(ctx, build_env, extra_environ, req, sdist_root_dir):
    with tempfile.TemporaryDirectory() as dir_name:
        cmd = [
            build_env.python, '-m', 'pip', '-vvv',
            '--disable-pip-version-check',
            'wheel',
            '--no-cache-dir',
            '--no-build-isolation',
            '--only-binary', ':all:',
            '--wheel-dir', ctx.wheels_build,
            '--no-deps',
            '--index-url', ctx.wheel_server_url,  # probably redundant, but just in case
            sdist_root_dir,
        ]
        external_commands.run(cmd, cwd=dir_name, extra_environ=extra_environ)


class BuildEnvironment:
    "Wrapper for a virtualenv used for build isolation."

    def __init__(self, ctx, parent_dir, build_requirements):
        self._ctx = ctx
        self.path = parent_dir / f'build-{platform.python_version()}'
        self._build_requirements = build_requirements
        self._createenv()

    @property
    def python(self):
        return (self.path / 'bin/python3').absolute()

    def _createenv(self):
        if self.path.exists():
            logger.info('reusing build environment in %s', self.path)
            return
        logger.debug('creating build environment in %s', self.path)
        self._builder = venv.EnvBuilder(clear=True, with_pip=True)
        self._builder.create(self.path)
        logger.info('created build environment in %s', self.path)
        req_filename = self.path / 'requirements.txt'
        # FIXME: Ensure each requirement is pinned to a specific version.
        with open(req_filename, 'w') as f:
            if self._build_requirements:
                for r in self._build_requirements:
                    f.write(f'{r}\n')
        if not self._build_requirements:
            return
        external_commands.run(
            [self.python, '-m', 'pip',
             'install',
             '--disable-pip-version-check',
             '--no-cache-dir',
             '--only-binary', ':all:',
             ] + self._ctx.pip_wheel_server_args + [
                 '-r', req_filename.absolute(),
             ],
            cwd=self.path.parent,
        )
        logger.info('installed dependencies into build environment in %s', self.path)
