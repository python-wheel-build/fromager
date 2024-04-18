import logging

import resolvelib

from mirror_builder import resolver, sources

logger = logging.getLogger(__name__)


# Note that we're downloading a PyTorch release tarball that is not strictly an
# sdist. Instead it's an archive of the git repo produced by the create_release
# workflow which (crucially) includes the third_party/ submodules.
def download_source(ctx, req):
    provider = resolver.PyPIProvider(only_sdists=False)
    reporter = resolvelib.BaseReporter()
    rslvr = resolvelib.Resolver(provider, reporter)

    logger.debug("resolving requirement %s", req)
    try:
        result = rslvr.resolve([req])
    except (resolvelib.InconsistentCandidate,
            resolvelib.RequirementsConflicted,
            resolvelib.ResolutionImpossible) as err:
        logger.warning(f'could not resolve {req}: {err}')
        raise

    for _, candidate in result.mapping.items():
        logger.info(f"resolved {req} to {candidate.version}")
        return sources.download_url(ctx.sdists_downloads,
                                    _get_pytorch_release_tarball_url(candidate.version))


def _get_pytorch_release_tarball_url(version):
    return f"https://github.com/pytorch/pytorch/releases/download/v{version}/pytorch-v{version}.tar.gz"
