import importlib.metadata
import logging
import shutil
import sys

from . import dependencies, external_commands, finders, server, sources, wheels

logger = logging.getLogger(__name__)


class MissingDependency(Exception):

    def __init__(self, req_type, req, all_reqs):
        self.missing_req = req
        self.all_reqs = all_reqs
        resolutions = []
        for r in all_reqs:
            try:
                url, version = sources.resolve_sdist(r, sources.PYPI_SERVER_URL)
            except Exception as err:
                resolutions.append(f'{r} -> {err}')
            else:
                resolutions.append(f'{r} -> {version}')
        formatted_reqs = '\n'.join(resolutions)
        msg = (
            f'Failed to install {req_type} dependency {req}. '
            f'Check all {req_type} dependencies:\n{formatted_reqs}'
        )
        super().__init__(f'\n{"*" * 40}\n{msg}\n{"*" * 40}\n')


def handle_requirement(ctx, req, req_type='toplevel', why=''):
    source_filename, resolved_version = sources.download_source(
        ctx, req, sources.DEFAULT_SDIST_SERVER_URLS)

    # Avoid cyclic dependencies and redundant processing.
    if ctx.has_been_seen(req, resolved_version):
        logger.debug(f'redundant requirement {req} resolves to {resolved_version}')
        return resolved_version
    ctx.mark_as_seen(req, resolved_version)

    logger.info('new dependency (%s) %s -> %s resolves to %s', req_type, why, req, resolved_version)

    sdist_root_dir = sources.prepare_source(ctx, req, source_filename, resolved_version)

    next_why = f'{why} -> {req.name}({resolved_version})'
    next_req_type = 'build_system'
    build_system_dependencies = dependencies.get_build_system_dependencies(ctx, req, sdist_root_dir)
    _write_requirements_file(
        build_system_dependencies,
        sdist_root_dir.parent / 'build-system-requirements.txt',
    )
    for dep in build_system_dependencies:
        try:
            resolved = handle_requirement(ctx, dep, next_req_type, next_why)
        except Exception as err:
            raise ValueError(f'could not handle {next_req_type} dependency {dep} for {next_why}') from err
        # We may need these dependencies installed in order to run build hooks
        # Example: frozenlist build-system.requires includes expandvars because
        # it is used by the packaging/pep517_backend/ build backend
        _maybe_install(ctx, dep, next_req_type, resolved)

    next_req_type = 'build_backend'
    build_backend_dependencies = dependencies.get_build_backend_dependencies(ctx, req, sdist_root_dir)
    _write_requirements_file(
        build_backend_dependencies,
        sdist_root_dir.parent / 'build-backend-requirements.txt',
    )
    for dep in build_backend_dependencies:
        try:
            resolved = handle_requirement(ctx, dep, next_req_type, next_why)
        except Exception as err:
            raise ValueError(f'could not handle {next_req_type} dependency {dep} for {next_why}') from err
        # Build backends are often used to package themselves, so in
        # order to determine their dependencies they may need to be
        # installed.
        _maybe_install(ctx, dep, next_req_type, resolved)

    # Add the new package to the build order list before trying to
    # build it so we have a record of the dependency even if the build
    # fails.
    ctx.add_to_build_order(req_type, req, resolved_version, why)

    # FIXME: This is a bit naive, but works for most wheels, including
    # our more expensive ones, and there's not a way to know the
    # actual name without doing most of the work to build the wheel.
    wheel_filename = finders.find_wheel(ctx.wheels_downloads, req, resolved_version)
    if wheel_filename:
        logger.info('have wheel for %s version %s: %s',
                    req.name, resolved_version, wheel_filename)
        build_env = None  # for cleanup
    else:
        logger.info('preparing to build wheel for %s version %s', req, resolved_version)
        build_env = wheels.BuildEnvironment(
            ctx, sdist_root_dir.parent,
            build_system_dependencies | build_backend_dependencies,
        )
        built_filename = wheels.build_wheel(ctx, req, sdist_root_dir, build_env)
        server.update_wheel_mirror(ctx)
        # When we update the mirror, the built file moves to the
        # downloads directory.
        wheel_filename = ctx.wheels_downloads / built_filename.name
        logger.info('built wheel for %s version %s: %s',
                    req.name, resolved_version, wheel_filename)

    next_req_type = 'dependency'
    install_dependencies = dependencies.get_install_dependencies_of_wheel(wheel_filename)
    _write_requirements_file(
        install_dependencies,
        sdist_root_dir.parent / 'requirements.txt',
    )
    for dep in install_dependencies:
        try:
            handle_requirement(ctx, dep, next_req_type, next_why)
        except Exception as err:
            raise ValueError(f'could not handle {next_req_type} dependency {dep} for {next_why}') from err

    # Cleanup the source tree and build environment, leaving any other
    # artifacts that were created.
    if ctx.cleanup:
        logger.debug('cleaning up source tree %s', sdist_root_dir)
        shutil.rmtree(sdist_root_dir)
        logger.debug('cleaned up source tree %s', sdist_root_dir)
        if build_env:
            logger.debug('cleaning up build environment %s', build_env.path)
            shutil.rmtree(build_env.path)
            logger.debug('cleaned up build environment %s', build_env.path)

    return resolved_version


def prepare_build_environment(ctx, req, sdist_root_dir):
    logger.info('preparing build environment for %s', req.name)

    next_req_type = 'build_system'
    build_system_dependencies = dependencies.get_build_system_dependencies(ctx, req, sdist_root_dir)
    _write_requirements_file(
        build_system_dependencies,
        sdist_root_dir.parent / 'build-system-requirements.txt',
    )
    for dep in build_system_dependencies:
        # We may need these dependencies installed in order to run build hooks
        # Example: frozenlist build-system.requires includes expandvars because
        # it is used by the packaging/pep517_backend/ build backend
        try:
            _maybe_install(ctx, dep, next_req_type, None)
        except Exception as err:
            logger.error('failed to install %s dependency %s: %s', next_req_type, dep, err)
            raise MissingDependency(next_req_type, dep, build_system_dependencies) from err

    next_req_type = 'build_backend'
    build_backend_dependencies = dependencies.get_build_backend_dependencies(ctx, req, sdist_root_dir)
    _write_requirements_file(
        build_backend_dependencies,
        sdist_root_dir.parent / 'build-backend-requirements.txt',
    )
    for dep in build_backend_dependencies:
        # Build backends are often used to package themselves, so in
        # order to determine their dependencies they may need to be
        # installed.
        try:
            _maybe_install(ctx, dep, next_req_type, None)
        except Exception as err:
            logger.error('failed to install %s dependency %s: %s', next_req_type, dep, err)
            raise MissingDependency(next_req_type, dep, build_backend_dependencies) from err

    build_env = wheels.BuildEnvironment(
        ctx, sdist_root_dir.parent,
        build_system_dependencies | build_backend_dependencies,
    )
    return build_env.path


def _write_requirements_file(requirements, filename):
    with open(filename, 'w') as f:
        for r in requirements:
            f.write(f'{r}\n')


def _maybe_install(ctx, req, req_type, resolved_version):
    "Install the package if it is not already installed."
    if resolved_version is not None:
        try:
            actual_version = importlib.metadata.version(req.name)
            if str(resolved_version) == actual_version:
                logger.debug('already have %s %s installed', req.name, resolved_version)
                return
            logger.info('found %s %s installed, updating to %s',
                        req.name, actual_version, resolved_version)
        except importlib.metadata.PackageNotFoundError as err:
            logger.debug('could not determine version of %s: %s', req.name, err)
    safe_install(ctx, req, req_type)


def safe_install(ctx, req, req_type):
    logger.debug('installing %s %s', req_type, req)
    external_commands.run([
        sys.executable, '-m', 'pip',
        '-vvv',
        'install',
        '--disable-pip-version-check',
        '--no-cache-dir',
        '--upgrade',
        '--only-binary', ':all:',
    ] + ctx.pip_wheel_server_args + [
        f'{req}',
    ])
    version = importlib.metadata.version(req.name)
    logger.info('installed %s %s using %s', req_type, req, version)
