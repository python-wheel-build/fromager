import inspect
import json
import logging
import os.path
import pathlib
import shutil
import subprocess
import tarfile
import zipfile
from urllib.parse import urlparse

import requests
import resolvelib

from . import overrides, resolver, vendor_rust

logger = logging.getLogger(__name__)

PYPI_SERVER_URL = 'https://pypi.org/simple'
PYAI_SOURCE_SERVER_URL = 'https://pyai.fedorainfracloud.org/experimental/sources/+simple/'
DEFAULT_SDIST_SERVER_URLS = [
    PYPI_SERVER_URL,
    PYAI_SOURCE_SERVER_URL,
]


def download_source(ctx, req, sdist_server_urls):
    downloader = overrides.find_override_method(req.name, 'download_source')
    source_type = 'override'
    if not downloader:
        downloader = default_download_source
        source_type = 'sdist'
    for url in sdist_server_urls:
        try:
            logger.debug('trying to resolve and download %s using %s', req, url)
            download_details = downloader(ctx, req, url)
            if len(download_details) == 3:
                source_filename, version, source_url = download_details
            elif len(download_details) == 2:
                source_filename, version = download_details
                source_url = 'override'
            else:
                raise ValueError(f'do not know how to unpack {download_details}, expected 2 or 3 members')
        except Exception as err:
            logger.debug('failed to resolve %s using %s: %s', req, url, err)
            continue
        return (source_filename, version, source_url, source_type)
    servers = ', '.join(sdist_server_urls)
    raise ValueError(f'failed to find source for {req} at {servers}')


def resolve_sdist(req, sdist_server_url, only_sdists=True):
    "Return URL to source and its version."
    # Create the (reusable) resolver. Limit to sdists.
    provider = resolver.PyPIProvider(only_sdists=only_sdists, sdist_server_url=sdist_server_url)
    reporter = resolvelib.BaseReporter()
    rslvr = resolvelib.Resolver(provider, reporter)

    # Kick off the resolution process, and get the final result.
    logger.debug("resolving requirement %s using %s", req, sdist_server_url)
    try:
        result = rslvr.resolve([req])
    except (resolvelib.InconsistentCandidate,
            resolvelib.RequirementsConflicted,
            resolvelib.ResolutionImpossible) as err:
        logger.warning(f'could not resolve {req}: {err}')
        raise

    for name, candidate in result.mapping.items():
        return (candidate.url, candidate.version)
    return (None, None)


def default_download_source(ctx, req, sdist_server_url):
    "Download the requirement and return the name of the output path."
    url, version = resolve_sdist(req, sdist_server_url)
    source_filename = download_url(ctx.sdists_downloads, url)
    logger.debug('have source for %s version %s in %s', req, version, source_filename)
    return (source_filename, version, url)


def download_url(destination_dir, url):
    outfile = pathlib.Path(destination_dir) / os.path.basename(urlparse(url).path)
    logger.debug('looking for %s %s',
                 outfile,
                 '(exists)' if outfile.exists() else '(not there)')
    if outfile.exists():
        logger.debug(f'already have {outfile}')
        return outfile
    # Open the URL first in case that fails, so we don't end up with an empty file.
    logger.debug(f'reading from {url}')
    with requests.get(url, stream=True) as r:
        with open(outfile, 'wb') as f:
            logger.debug(f'writing to {outfile}')
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
    logger.info(f'saved {outfile}')
    return outfile


def _sdist_root_name(source_filename):
    base_name = pathlib.Path(source_filename).name
    if base_name.endswith('.tar.gz'):
        ext_to_strip = '.tar.gz'
    elif base_name.endswith('.zip'):
        ext_to_strip = '.zip'
    else:
        raise ValueError(f'Do not know how to work with {source_filename}')
    return base_name[:-len(ext_to_strip)]


def _takes_arg(f, arg_name):
    sig = inspect.signature(f)
    return arg_name in sig.parameters


def unpack_source(ctx, source_filename):
    unpack_dir = ctx.work_dir / _sdist_root_name(source_filename)
    if unpack_dir.exists():
        if ctx.cleanup:
            logger.debug('cleaning up %s', unpack_dir)
            shutil.rmtree(unpack_dir)
        else:
            logger.info('reusing %s', unpack_dir)
            return (unpack_dir / unpack_dir.name, False)
    # We create a unique directory based on the sdist name, but that
    # may not be the same name as the root directory of the content in
    # the sdist (due to case, punctuation, etc.), so after we unpack
    # it look for what was created.
    logger.debug('unpacking %s to %s', source_filename, unpack_dir)
    if str(source_filename).endswith('.tar.gz'):
        with tarfile.open(source_filename, 'r') as t:
            if _takes_arg(t.extractall, 'filter'):
                t.extractall(unpack_dir, filter='data')
            else:
                logger.debug('unpacking without filter="data"')
                t.extractall(unpack_dir)
    elif str(source_filename).endswith('.zip'):
        with zipfile.ZipFile(source_filename) as zf:
            zf.extractall(path=unpack_dir)
    else:
        raise ValueError(f'Do not know how to unpack source archive {source_filename}')
    return (list(unpack_dir.glob('*'))[0], True)


def _patch_source(ctx, source_root_dir):
    for p in overrides.patches_for_source_dir(ctx.patches_dir, source_root_dir.name):
        logger.info('applying patch file %s to %s', p, source_root_dir)
        with open(p, 'r') as f:
            subprocess.check_call(
                ['patch', '-p1'],
                stdin=f,
                cwd=source_root_dir,
            )


def write_build_meta(unpack_dir, req, source_filename, version):
    meta_file = unpack_dir / 'build-meta.json'
    with open(meta_file, 'w') as f:
        json.dump(
            {
                "req": str(req),
                "source-filename": str(source_filename),
                "version": str(version),
            },
            f,
        )
    logger.debug('wrote build metadata to %s', meta_file)
    return meta_file


def read_build_meta(unpack_dir):
    meta_file = unpack_dir / 'build-meta.json'
    with open(meta_file, 'r') as f:
        return json.load(f)


def prepare_source(ctx, req, source_filename, version):
    logger.info('preparing source for %s from %s', req, source_filename)
    preparer = overrides.find_override_method(req.name, 'prepare_source')
    if not preparer:
        preparer = _default_prepare_source
    source_root_dir = preparer(ctx, req, source_filename, version)
    write_build_meta(source_root_dir.parent, req, source_filename, version)
    if source_root_dir is not None:
        logger.info('prepared source for %s at %s', req, source_root_dir)
    return source_root_dir


def _default_prepare_source(ctx, req, source_filename, version):
    source_root_dir, is_new = unpack_source(ctx, source_filename)
    if is_new:
        _patch_source(ctx, source_root_dir)
        vendor_rust.vendor_rust(source_root_dir)
    return source_root_dir
