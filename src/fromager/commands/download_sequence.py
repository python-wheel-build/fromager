import logging
import json

import click
from packaging.requirements import Requirement

from .. import sources

logger = logging.getLogger(__name__)


@click.command()
@click.argument('build_order_file')
@click.argument('sdist_server_url')
@click.pass_obj
def download_sequence(wkctx, build_order_file, sdist_server_url):
    """Download a sequence of source distributions in order.

    BUILD_ORDER_FILE is the build-order.json files to build

    SDIST_SERVER_URL is the URL for a PyPI-compatible package index hosting sdists

    Performs the equivalent of the 'step download-source-archive' command for each item in
    the build order file.

    """
    with open(build_order_file, 'r') as f:
        for entry in json.load(f):
            req = Requirement(f"{entry['dist']}=={entry['version']}")
            sources.download_source(wkctx, req, [sdist_server_url])