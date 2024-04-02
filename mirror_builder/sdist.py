import importlib.metadata
import logging
import pathlib
import shutil
import subprocess
import tarfile

import resolvelib

from . import dependencies, external_commands, resolve_and_download, wheels

logger = logging.getLogger(__name__)


def handle_requirement(ctx, req, why='', req_type='toplevel'):
    sdist_filename = download_sdist(ctx, req)
    return _collect_build_requires(ctx, req_type, req, sdist_filename, why)


def _collect_build_requires(ctx, req_type, req, sdist_filename, why):
    # Avoid cyclic dependencies and redundant processing.
    resolved_name = _get_resolved_name(sdist_filename)
    if ctx.has_been_seen(resolved_name):
        logger.info('existing dependency %s -> %s resolves to %s', why, req, resolved_name)
        return resolved_name
    ctx.mark_as_seen(resolved_name)
    logger.info('new dependency %s -> %s resolves to %s', why, req, resolved_name)

    next_why = f'{why} -> {resolved_name}'

    sdist_root_dir = unpack_sdist(ctx, sdist_filename)

    build_system_dependencies = dependencies.get_build_system_dependencies(req, sdist_root_dir)
    _write_requirements_file(
        build_system_dependencies,
        sdist_root_dir.parent / 'build-system-requirements.txt',
    )
    for dep in build_system_dependencies:
        resolved = handle_requirement(ctx=ctx, req=dep, why=next_why, req_type=req_type)
        # We may need these dependencies installed in order to run build hooks
        # Example: frozenlist build-system.requires includes expandvars because
        # it is used by the packaging/pep517_backend/ build backend
        _maybe_install(ctx, dep, 'build_system', resolved)

    build_backend_dependencies = dependencies.get_build_backend_dependencies(req, sdist_root_dir)
    _write_requirements_file(
        build_backend_dependencies,
        sdist_root_dir.parent / 'build-backend-requirements.txt',
    )
    for dep in build_backend_dependencies:
        resolved = handle_requirement(ctx=ctx, req=dep, why=next_why, req_type=req_type)
        # Build backends are often used to package themselves, so in
        # order to determine their dependencies they may need to be
        # installed.
        _maybe_install(ctx, dep, 'build_backend', resolved)

    wheels.build_wheel(ctx, req_type, req, resolved_name, why, sdist_root_dir)

    install_dependencies = dependencies.get_install_dependencies(req, sdist_root_dir)
    _write_requirements_file(
        install_dependencies,
        sdist_root_dir.parent / 'requirements.txt',
    )
    for dep in install_dependencies:
        handle_requirement(ctx=ctx, req=dep, why=next_why, req_type=req_type)

    return resolved_name


def _get_resolved_name(sdist_filename):
    return pathlib.Path(sdist_filename).name[:-len('.tar.gz')]


def _write_requirements_file(requirements, filename):
    with open(filename, 'w') as f:
        for r in requirements:
            f.write(f'{r}\n')


def _maybe_install(ctx, req, req_type, resolved_name):
    "Install the package if it is not already installed."
    try:
        version = importlib.metadata.version(req.name)
        actual_version = f'{req.name}-{version}'
        if resolved_name == actual_version:
            return
    except importlib.metadata.PackageNotFoundError:
        pass
    safe_install(ctx, req, req_type)


def safe_install(ctx, req, req_type):
    logger.debug('installing %s %s', req_type, req)
    external_commands.run([
        'pip', '-vvv',
        'install',
        '--disable-pip-version-check',
        '--no-cache-dir',
        '--upgrade',
        '--only-binary', ':all:',
        '--index-url', ctx.wheel_server_url,
        f'{req}',
    ])
    version = importlib.metadata.version(req.name)
    logger.info('installed %s %s using %s', req_type, req, version)


def unpack_sdist(ctx, sdist_filename):
    unpack_dir = ctx.work_dir / pathlib.Path(sdist_filename).stem[:-len('.tar')]
    if unpack_dir.exists():
        shutil.rmtree(unpack_dir)
        logger.debug('cleaning up %s', unpack_dir)
    # We create a unique directory based on the sdist name, but that
    # may not be the same name as the root directory of the content in
    # the sdist (due to case, punctuation, etc.), so after we unpack
    # it look for what was created.
    logger.debug('unpacking %s to %s', sdist_filename, unpack_dir)
    with tarfile.open(sdist_filename, 'r') as t:
        t.extractall(unpack_dir)
    sdist_root_dir = list(unpack_dir.glob('*'))[0]
    _patch_sdist(ctx, sdist_root_dir)
    return sdist_root_dir


def _patch_sdist(ctx, sdist_root_dir):
    for p in pathlib.Path('patches').glob(sdist_root_dir.name + '*.patch'):
        logger.info('applying patch file %s to %s', p, sdist_root_dir)
        with open(p, 'r') as f:
            subprocess.check_call(
                ['patch', '-p1'],
                stdin=f,
                cwd=sdist_root_dir,
            )


def download_sdist(ctx, requirement):
    "Download the requirement and return the name of the output path."

    # Create the (reusable) resolver.
    provider = resolve_and_download.PyPIProvider()
    reporter = resolve_and_download.BaseReporter()
    resolver = resolvelib.Resolver(provider, reporter)

    # Kick off the resolution process, and get the final result.
    logger.debug("resolving requirement %s", requirement)
    try:
        result = resolver.resolve([requirement])
    except (resolvelib.InconsistentCandidate,
            resolvelib.RequirementsConflicted,
            resolvelib.ResolutionImpossible) as err:
        logger.warning(f'could not resolve {requirement}: {err}')
    else:
        return resolve_and_download.download_resolution(
            ctx.sdists_downloads,
            result,
        )
