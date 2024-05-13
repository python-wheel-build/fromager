import logging

from mirror_builder import sources, wheels

logger = logging.getLogger(__name__)


# Note that we're downloading a PyTorch release tarball that is not strictly an
# sdist. Instead it's an archive of the git repo produced by the create_release
# workflow which (crucially) includes the third_party/ submodules.
def download_source(ctx, req, sdist_server_url):
    # Downloading source from upstream is the special case
    # if "pypi.org" not in sdist_server_url:
    #     return sources.default_download_source(ctx, req, sdist_server_url)

    _, version = sources.resolve_sdist(
        req,
        # sdist_server_url,
        sources.PYPI_SERVER_URL,  # always look upstream since we have no sdists
        only_sdists=False,
    )
    logger.info(f"resolved {req} to {version}")
    source_filename = sources.download_url(
        ctx.sdists_downloads,
        _get_pytorch_release_tarball_url(version),
    )
    logger.info('have source for %s version %s in %s', req, version, source_filename)
    return source_filename, version


def _get_pytorch_release_tarball_url(version):
    return f"https://github.com/pytorch/pytorch/releases/download/v{version}/pytorch-v{version}.tar.gz"


def expected_source_archive_name(req, dist_version):
    return f'pytorch-v{dist_version}.tar.gz'


def build_wheel(ctx, build_env, extra_environ, req, sdist_root_dir):
    # Force the version to match so we don't get alpha and git tag
    # info included.
    metadata = sources.read_build_meta(sdist_root_dir.parent)
    extra_environ['PYTORCH_BUILD_VERSION'] = metadata['version']
    # The build number must be set if build version is set. Using a
    # number greater than 1 triggers appending a '.post'
    # version. Refer to 'get_torch_version' in
    # tools/generate_torch_version.py in the torch source tree for
    # details.
    extra_environ['PYTORCH_BUILD_NUMBER'] = '0'
    return wheels.default_build_wheel(ctx, build_env, extra_environ, req, sdist_root_dir)
