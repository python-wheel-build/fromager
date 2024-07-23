"""Tools for looking for system packages related to python packages being built."""

import collections
import logging

from . import external_commands

logger = logging.getLogger(__name__)


def list_rpms() -> dict[str, list[str]]:
    """Return dictionary mapping RPM name to version(s)."""
    logger.debug("getting list of rpms available to this host")
    repoquery = external_commands.run(
        [
            "dnf",
            "repoquery",
            "--quiet",
            "--queryformat",
            "%{name},%{version}",
        ]
    )
    rpms = collections.defaultdict(list)
    for line in repoquery.splitlines():
        line = line.strip()
        name, version = line.split(",", 1)
        rpms[name].append(version)
    return rpms
