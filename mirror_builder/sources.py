import logging

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
