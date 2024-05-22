import importlib.metadata
import logging
import os.path
import shutil
import sys
from urllib.parse import urlparse

from . import dependencies, external_commands, finders, server, sources, wheels
from .pkgs import overrides

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


def _pkg_name_set(names):
    return set(overrides.pkgname_to_override_module(n) for n in names)


# Depending on the variant, some pre-built wheels aren't built from
# source and must be acquired from another package index.
PRE_BUILT = {
    'cuda': _pkg_name_set([
        # requires aligning versions with external tools
        'llvmlite',

        # Not open source?
        'nvidia-cublas-cu12',
        'nvidia-cuda-cupti-cu12',
        'nvidia-cuda-nvrtc-cu12',
        'nvidia-cuda-runtime-cu12',
        'nvidia-cudnn-cu12',
        'nvidia-cufft-cu12',
        'nvidia-curand-cu12',
        'nvidia-cusolver-cu12',
        'nvidia-cusparse-cu12',
        'nvidia-nccl-cu12',
        'nvidia-nvjitlink-cu12',
        'nvidia-nvtx-cu12',

        # requires rustc 1.76 or newer, not available in UBI9
        'pydantic-core',

        # The builds work for older versions, but not for 2.3, yet.
        'torch',
        'triton',
        # vllm's setup.py computes the CUDA dependencies dynamically
        # based on the CUDA version it gets from importing torch. The
        # container image knows how to build vllm with all sorts of
        # pre-build setup steps, so we don't try to do it ourself.
        'vllm',
    ]),
}


def handle_requirement(ctx, req, req_type='toplevel', why=None):
    if why is None:
        why = []
    logger.info(f'{"*" * (len(why) + 1)} handling {req_type} requirement {req} {why}')

    pre_built = overrides.pkgname_to_override_module(req.name) in PRE_BUILT.get(ctx.variant, set())

    # Resolve the dependency and get either the pre-built wheel our
    # the source code.
    if not pre_built:
        source_filename, resolved_version = sources.download_source(
            ctx, req, sources.DEFAULT_SDIST_SERVER_URLS)

    else:
        logger.info(f'{req_type} requirement {req} uses a pre-built wheel')
        # FIXME: Do we need an option for prebuilt wheel server in
        # case these do not come from PyPI?
        wheel_url, resolved_version = sources.resolve_sdist(
            req, sources.PYPI_SERVER_URL, only_sdists=False)
        wheel_filename = ctx.wheels_prebuilt / os.path.basename(urlparse(wheel_url).path)
        if not wheel_filename.exists():
            logger.info(f'downloading pre-built wheel {wheel_url}')
            wheel_filename = sources.download_url(ctx.wheels_prebuilt, wheel_url)
        else:
            logger.info(f'have pre-built wheel {wheel_filename}')
        # Add the wheel to the mirror so it is available to anything
        # that needs to install it. We leave a copy in the prebuilt
        # directory to make it easy to remove the wheel from the
        # downloads directory before uploading to a proper package
        # index.
        dest_name = ctx.wheels_downloads / wheel_filename.name
        if not dest_name.exists():
            logger.info('updating temporary mirror with pre-built wheel')
            shutil.copy(wheel_filename, dest_name)
            server.update_wheel_mirror(ctx)
        unpack_dir = ctx.work_dir / f'{req.name}-{resolved_version}'
        if not unpack_dir.exists():
            unpack_dir.mkdir()

    # Avoid cyclic dependencies and redundant processing.
    if ctx.has_been_seen(req, resolved_version):
        logger.debug(f'redundant {req_type} requirement {why} -> {req} resolves to {resolved_version}')
        return resolved_version
    ctx.mark_as_seen(req, resolved_version)

    logger.info('new %s dependency %s resolves to %s', req_type, req, resolved_version)

    # Build the dependency chain up to the point of this new
    # requirement using a new list so we can avoid modifying the list
    # we're given.
    why = why[:] + [(req_type, req, resolved_version)]

    # for cleanup
    build_env = None
    sdist_root_dir = None

    if not pre_built:
        sdist_root_dir = sources.prepare_source(ctx, req, source_filename, resolved_version)
        unpack_dir = sdist_root_dir.parent

        next_req_type = 'build_system'
        build_system_dependencies = _handle_build_system_requirements(ctx, req, why, sdist_root_dir)

        next_req_type = 'build_backend'
        build_backend_dependencies = _handle_build_backend_requirements(ctx, req, why, sdist_root_dir)

    # Add the new package to the build order list before trying to
    # build it so we have a record of the dependency even if the build
    # fails.
    ctx.add_to_build_order(req_type, req, resolved_version, why, pre_built)

    if not pre_built:
        # FIXME: This is a bit naive, but works for most wheels, including
        # our more expensive ones, and there's not a way to know the
        # actual name without doing most of the work to build the wheel.
        wheel_filename = finders.find_wheel(ctx.wheels_downloads, req, resolved_version)
        if wheel_filename:
            logger.info('have wheel for %s version %s: %s',
                        req.name, resolved_version, wheel_filename)
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

    # Process installation dependencies for all wheels.
    next_req_type = 'install'
    install_dependencies = dependencies.get_install_dependencies_of_wheel(req, wheel_filename)
    _write_requirements_file(
        install_dependencies,
        unpack_dir / 'requirements.txt',
    )
    for dep in install_dependencies:
        try:
            handle_requirement(ctx, dep, next_req_type, why)
        except Exception as err:
            raise ValueError(f'could not handle {next_req_type} dependency {dep} for {why}') from err

    # Cleanup the source tree and build environment, leaving any other
    # artifacts that were created.
    if ctx.cleanup:
        if sdist_root_dir:
            logger.debug('cleaning up source tree %s', sdist_root_dir)
            shutil.rmtree(sdist_root_dir)
            logger.debug('cleaned up source tree %s', sdist_root_dir)
        if build_env:
            logger.debug('cleaning up build environment %s', build_env.path)
            shutil.rmtree(build_env.path)
            logger.debug('cleaned up build environment %s', build_env.path)

    return resolved_version


def _handle_build_system_requirements(ctx, req, why, sdist_root_dir):
    build_system_dependencies = dependencies.get_build_system_dependencies(ctx, req, sdist_root_dir)
    _write_requirements_file(
        build_system_dependencies,
        sdist_root_dir.parent / 'build-system-requirements.txt',
    )
    for dep in build_system_dependencies:
        try:
            resolved = handle_requirement(ctx, dep, 'build-system', why)
        except Exception as err:
            raise ValueError(f'could not handle build-system dependency {dep} for {why}') from err
        # We may need these dependencies installed in order to run build hooks
        # Example: frozenlist build-system.requires includes expandvars because
        # it is used by the packaging/pep517_backend/ build backend
        _maybe_install(ctx, dep, 'build-system', resolved)
    return build_system_dependencies


def _handle_build_backend_requirements(ctx, req, why, sdist_root_dir):
    build_backend_dependencies = dependencies.get_build_backend_dependencies(ctx, req, sdist_root_dir)
    _write_requirements_file(
        build_backend_dependencies,
        sdist_root_dir.parent / 'build-backend-requirements.txt',
    )
    for dep in build_backend_dependencies:
        try:
            resolved = handle_requirement(ctx, dep, 'build-backend', why)
        except Exception as err:
            raise ValueError(f'could not handle build-backend dependency {dep} for {why}') from err
        # Build backends are often used to package themselves, so in
        # order to determine their dependencies they may need to be
        # installed.
        _maybe_install(ctx, dep, 'build-backend', resolved)
    return build_backend_dependencies


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
            logger.debug('could not determine version of %s, will install: %s', req.name, err)
    safe_install(ctx, req, req_type)


def safe_install(ctx, req, req_type):
    logger.debug('installing %s %s', req_type, req)
    external_commands.run([
        sys.executable, '-m', 'pip',
        '-vvv',
        'install',
        '--disable-pip-version-check',
        '--upgrade',
        '--only-binary', ':all:',
    ] + ctx.pip_wheel_server_args + [
        f'{req}',
    ])
    version = importlib.metadata.version(req.name)
    logger.info('installed %s %s using %s', req_type, req, version)
