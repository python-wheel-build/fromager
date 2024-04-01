# Based on https://github.com/sarugaku/resolvelib/blob/main/examples/pypi_wheel_provider.py
#
# Modified to look at sdists instead of wheels and to avoid trying to
# resolve any dependencies.
#
import argparse
import logging
import os.path
import re
import sys
from email.message import EmailMessage
from email.parser import BytesParser
from io import BytesIO
from operator import attrgetter
from platform import python_version
from urllib.parse import urlparse
from zipfile import ZipFile

import html5lib
import requests
from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from resolvelib import (BaseReporter, InconsistentCandidate,
                        RequirementsConflicted, ResolutionError,
                        ResolutionImpossible, Resolver)

from .extras_provider import ExtrasProvider

logger = logging.getLogger(__name__)

PYTHON_VERSION = Version(python_version())

NAME_VERSION_PATTERN = re.compile('(.*)-((\d+\.)+(\d+))\.tar\.gz')


class Candidate:
    def __init__(self, name, version, url=None, extras=None):
        self.name = canonicalize_name(name)
        self.version = version
        self.url = url
        self.extras = extras

        self._metadata = None
        self._dependencies = None

    def __repr__(self):
        if not self.extras:
            return f"<{self.name}=={self.version}>"
        return f"<{self.name}[{','.join(self.extras)}]=={self.version}>"

    @property
    def metadata(self):
        if self._metadata is None:
            self._metadata = get_metadata_for_wheel(self.url)
        return self._metadata

    @property
    def requires_python(self):
        return self.metadata.get("Requires-Python")

    def _get_dependencies(self):
        deps = self.metadata.get_all("Requires-Dist", [])
        extras = self.extras if self.extras else [""]

        for d in deps:
            r = Requirement(d)
            if r.marker is None:
                yield r
            else:
                for e in extras:
                    if r.marker.evaluate({"extra": e}):
                        yield r

    @property
    def dependencies(self):
        if self._dependencies is None:
            self._dependencies = list(self._get_dependencies())
        return self._dependencies


def get_project_from_pypi(project, extras):
    """Return candidates created from the project name and extras."""
    logger.debug('get available versions of project %s', project)
    url = "https://pypi.org/simple/{}".format(project)
    data = requests.get(url).content
    #log(data.decode('utf-8'))
    doc = html5lib.parse(data, namespaceHTMLElements=False)
    for i in doc.findall(".//a"):
        url = i.attrib["href"]
        py_req = i.attrib.get("data-requires-python")
        path = urlparse(url).path
        filename = path.rpartition("/")[-1]
        # Skip items that need a different Python version
        if py_req:
            try:
                spec = SpecifierSet(py_req)
            except InvalidSpecifier as err:
                # Ignore files with invalid python specifiers
                # e.g. shellingham has files with ">= '2.7'"
                log(f'skipping {filename} because of an invalid python version specifier {py_req}: {err}')
                continue
            if PYTHON_VERSION not in spec:
                logger.debug(f'skipping {filename} because of python version {py_req}')
                continue

        path = urlparse(url).path
        filename = path.rpartition("/")[-1]
        # Limit to sdists
        if not filename.endswith('.tar.gz'):
            continue

        # TODO: Handle compatibility tags?

        # Very primitive sdist filename parsing
        name_and_version = NAME_VERSION_PATTERN.search(filename)
        if not name_and_version:
            logger.debug(f'skipping {filename} because could not extract version info')
            continue
        name = name_and_version.groups()[0]
        version = name_and_version.groups()[1]
        try:
            version = Version(version)
        except InvalidVersion as err:
            # Ignore files with invalid versions
            logger.debug(f'invalid version for {filename}: {err}')
            continue

        c = Candidate(name, version, url=url, extras=extras)
        logger.debug('candidate %s (%s)', filename, c)
        yield c


def get_metadata_for_wheel(url):
    data = requests.get(url).content
    with ZipFile(BytesIO(data)) as z:
        for n in z.namelist():
            if n.endswith(".dist-info/METADATA"):
                p = BytesParser()
                return p.parse(z.open(n), headersonly=True)

    # If we didn't find the metadata, return an empty dict
    return EmailMessage()


class PyPIProvider(ExtrasProvider):
    def identify(self, requirement_or_candidate):
        return canonicalize_name(requirement_or_candidate.name)

    def get_extras_for(self, requirement_or_candidate):
        # Extras is a set, which is not hashable
        return tuple(sorted(requirement_or_candidate.extras))

    def get_base_requirement(self, candidate):
        return Requirement("{}=={}".format(candidate.name, candidate.version))

    def get_preference(self, identifier, resolutions, candidates, information, **kwds):
        return sum(1 for _ in candidates[identifier])

    def find_matches(self, identifier, requirements, incompatibilities):
        requirements = list(requirements[identifier])
        bad_versions = {c.version for c in incompatibilities[identifier]}

        # Need to pass the extras to the search, so they
        # are added to the candidate at creation - we
        # treat candidates as immutable once created.
        candidates = (
            candidate
            for candidate in get_project_from_pypi(identifier, set())
            if candidate.version not in bad_versions
            and all(candidate.version in r.specifier for r in requirements)
        )
        return sorted(candidates, key=attrgetter("version"), reverse=True)

    def is_satisfied_by(self, requirement, candidate):
        if canonicalize_name(requirement.name) != candidate.name:
            return False
        return candidate.version in requirement.specifier

    def get_dependencies(self, candidate):
        #return candidate.dependencies
        return []


def download_resolution(destination_dir, result):
    """Download the candidates"""
    for name, candidate in result.mapping.items():
        parsed_url = urlparse(candidate.url)
        outfile = os.path.join(destination_dir, os.path.basename(parsed_url.path))
        if os.path.exists(outfile):
            logger.debug(f'already have {outfile}')
            return outfile
        # Open the URL first in case that fails, so we don't end up with an empty file.
        logger.debug(f'reading {candidate.name} {candidate.version} from {candidate.url}')
        with requests.get(candidate.url, stream=True) as r:
            with open(outfile, 'wb') as f:
                logger.debug(f'writing to {outfile}')
                for chunk in r.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
            logger.debug(f'saved {outfile}')
            return outfile


def main():
    """Resolve requirements as project names on PyPI.

    The requirements are taken as command-line arguments
    and the resolution result will be printed to stdout.
    """
    global VERBOSE

    parser = argparse.ArgumentParser()
    parser.add_argument('--dest', default='.')
    parser.add_argument('requirements', nargs='+')
    parser.add_argument('-v', dest='verbose', action='store_true', default=False)
    args = parser.parse_args()

    VERBOSE = args.verbose

    # Things I want to resolve.
    requirements = [Requirement(r) for r in args.requirements]
    logger.basicConfig(
        level=logger.DEBUG if args.verbose else logging.INFO,
    )

    # Things I want to resolve.
    requirements = [Requirement(r) for r in args.requirements]

    # Create the (reusable) resolver.
    provider = PyPIProvider()
    reporter = BaseReporter()
    resolver = Resolver(provider, reporter)

    # Kick off the resolution process, and get the final result.
    logger.debug("Resolving %s", ", ".join(args.requirements))
    try:
        result = resolver.resolve(requirements)
    except (InconsistentCandidate, RequirementsConflicted, ResolutionImpossible) as err:
        print(f'could not resolve {requirements}: {err}', file=sys.stderr)
        sys.exit(1)
    else:
        download_resolution(args.dest, result)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
