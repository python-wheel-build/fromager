import logging
import pathlib
import shutil
import subprocess
import tarfile

import resolvelib

from . import resolve_and_download

logger = logging.getLogger(__name__)


def download_source(ctx, req):
    "Download the requirement and return the name of the output path."

    # Create the (reusable) resolver.
    provider = resolve_and_download.PyPIProvider()
    reporter = resolve_and_download.BaseReporter()
    resolver = resolvelib.Resolver(provider, reporter)

    # Kick off the resolution process, and get the final result.
    logger.debug("resolving requirement %s", req)
    try:
        result = resolver.resolve([req])
    except (resolvelib.InconsistentCandidate,
            resolvelib.RequirementsConflicted,
            resolvelib.ResolutionImpossible) as err:
        logger.warning(f'could not resolve {req}: {err}')
        raise
    else:
        return resolve_and_download.download_resolution(
            ctx.sdists_downloads,
            result,
        )


def unpack_source(ctx, source_filename):
    unpack_dir = ctx.work_dir / pathlib.Path(source_filename).stem[:-len('.tar')]
    if unpack_dir.exists():
        shutil.rmtree(unpack_dir)
        logger.debug('cleaning up %s', unpack_dir)
    # We create a unique directory based on the sdist name, but that
    # may not be the same name as the root directory of the content in
    # the sdist (due to case, punctuation, etc.), so after we unpack
    # it look for what was created.
    logger.debug('unpacking %s to %s', source_filename, unpack_dir)
    with tarfile.open(source_filename, 'r') as t:
        t.extractall(unpack_dir, filter='data')
    source_root_dir = list(unpack_dir.glob('*'))[0]
    _patch_source(ctx, source_root_dir)
    return source_root_dir


def _patch_source(ctx, source_root_dir):
    for p in pathlib.Path('patches').glob(source_root_dir.name + '*.patch'):
        logger.info('applying patch file %s to %s', p, source_root_dir)
        with open(p, 'r') as f:
            subprocess.check_call(
                ['patch', '-p1'],
                stdin=f,
                cwd=source_root_dir,
            )
