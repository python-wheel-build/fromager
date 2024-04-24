import logging
import os.path
import pathlib
import shutil
import subprocess
import tarfile
from urllib.parse import urlparse

import requests
import resolvelib

from . import pkgs, resolver

logger = logging.getLogger(__name__)


def download_source(ctx, req):
    logger.info('downloading source for %s', req)
    downloader = pkgs.find_override_method(req.name, 'download_source')
    if not downloader:
        downloader = _default_download_source
    source_filename, version = downloader(ctx, req)
    logger.info('downloaded source for %s version %s to %s', req, version, source_filename)
    return (source_filename, version)


def resolve_sdist(req):
    "Return URL to source and its version."
    # Create the (reusable) resolver. Limit to sdists.
    provider = resolver.PyPIProvider(only_sdists=True)
    reporter = resolvelib.BaseReporter()
    rslvr = resolvelib.Resolver(provider, reporter)

    # Kick off the resolution process, and get the final result.
    logger.debug("resolving requirement %s", req)
    try:
        result = rslvr.resolve([req])
    except (resolvelib.InconsistentCandidate,
            resolvelib.RequirementsConflicted,
            resolvelib.ResolutionImpossible) as err:
        logger.warning(f'could not resolve {req}: {err}')
        raise

    for name, candidate in result.mapping.items():
        return (candidate.url, candidate.version)


def _default_download_source(ctx, req):
    "Download the requirement and return the name of the output path."
    url, version = resolve_sdist(req)
    return (download_url(ctx.sdists_downloads, url), version)


def download_url(destination_dir, url):
    outfile = os.path.join(destination_dir, os.path.basename(urlparse(url).path))
    if os.path.exists(outfile):
        logger.debug(f'already have {outfile}')
        return outfile
    # Open the URL first in case that fails, so we don't end up with an empty file.
    logger.debug(f'reading from {url}')
    with requests.get(url, stream=True) as r:
        with open(outfile, 'wb') as f:
            logger.debug(f'writing to {outfile}')
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
        logger.debug(f'saved {outfile}')
        return outfile


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
    return list(unpack_dir.glob('*'))[0]


def _patch_source(ctx, source_root_dir):
    for p in pkgs.patches_for_source_dir(source_root_dir.name):
        logger.info('applying patch file %s to %s', p, source_root_dir)
        with open(p, 'r') as f:
            subprocess.check_call(
                ['patch', '-p1'],
                stdin=f,
                cwd=source_root_dir,
            )


def prepare_source(ctx, req, source_filename, version):
    logger.info('preparing source for %s from %s', req, source_filename)
    preparer = pkgs.find_override_method(req.name, 'prepare_source')
    if not preparer:
        preparer = _default_prepare_source
    source_root_dir = preparer(ctx, req, source_filename, version)
    if source_root_dir is not None:
        logger.info('prepared source for %s at %s', req, source_root_dir)
    return source_root_dir


def _default_prepare_source(ctx, req, source_filename, version):
    source_root_dir = unpack_source(ctx, source_filename)
    _patch_source(ctx, source_root_dir)
    return source_root_dir
