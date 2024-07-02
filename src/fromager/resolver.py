# Based on https://github.com/sarugaku/resolvelib/blob/main/examples/pypi_wheel_provider.py
#
# Modified to look at sdists instead of wheels and to avoid trying to
# resolve any dependencies.
#
import logging
import os
import typing
from email.message import EmailMessage
from email.parser import BytesParser
from io import BytesIO
from operator import attrgetter
from platform import python_version
from urllib.parse import urljoin, urlparse
from zipfile import ZipFile

import github
import html5lib
import requests
from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.tags import sys_tags
from packaging.utils import (
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import Version

from .extras_provider import ExtrasProvider

logger = logging.getLogger(__name__)

PYTHON_VERSION = Version(python_version())
DEBUG_RESOLVER = os.environ.get("DEBUG_RESOLVER", "")
SUPPORTED_TAGS = set(sys_tags())


class Candidate:
    def __init__(
        self,
        name: str,
        version: str,
        url: str | None = None,
        extras: dict | None = None,
        is_sdist: bool | None = None,
    ):
        self.name = canonicalize_name(name)
        self.version = version
        self.url = url
        self.extras = extras
        self.is_sdist = is_sdist

        self._metadata = None
        self._dependencies = None

    def __repr__(self) -> str:
        if not self.extras:
            return f"<{self.name}=={self.version}>"
        return f"<{self.name}[{','.join(self.extras)}]=={self.version}>"

    @property
    def metadata(self):
        if self._metadata is None:
            self._metadata = get_metadata_for_wheel(self.url)
        return self._metadata

    @property
    def requires_python(self) -> bool:
        return self.metadata.get("Requires-Python")

    def _get_dependencies(self) -> typing.Iterable[Requirement]:
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
    def dependencies(self) -> list[Requirement]:
        if self._dependencies is None:
            self._dependencies = list(self._get_dependencies())
        return self._dependencies


def get_project_from_pypi(
    project: str,
    extras: tuple[str],
    sdist_server_url: str,
) -> typing.Iterable[Candidate]:
    """Return candidates created from the project name and extras."""
    simple_index_url = sdist_server_url.rstrip("/") + "/" + project + "/"
    logger.debug(
        "get available versions of project %s from %s", project, simple_index_url
    )
    data = requests.get(simple_index_url).content
    doc = html5lib.parse(data, namespaceHTMLElements=False)
    for i in doc.findall(".//a"):
        candidate_url = urljoin(simple_index_url, i.attrib["href"])
        py_req = i.attrib.get("data-requires-python")
        path = urlparse(candidate_url).path
        filename = path.rpartition("/")[-1]
        if DEBUG_RESOLVER:
            logger.debug("candidate %r -> %r", candidate_url, filename)
        # Skip items that need a different Python version
        if py_req:
            try:
                spec = SpecifierSet(py_req)
            except InvalidSpecifier as err:
                # Ignore files with invalid python specifiers
                # e.g. shellingham has files with ">= '2.7'"
                if DEBUG_RESOLVER:
                    logger.debug(
                        f"skipping {filename} because of an invalid python version specifier {py_req}: {err}"
                    )
                continue
            if PYTHON_VERSION not in spec:
                if DEBUG_RESOLVER:
                    logger.debug(
                        f"skipping {filename} because of python version {py_req}"
                    )
                continue

        # TODO: Handle compatibility tags?

        try:
            if filename.endswith(".tar.gz") or filename.endswith(".zip"):
                is_sdist = True
                name, version = parse_sdist_filename(filename)
                tags = set()
            else:
                is_sdist = False
                name, version, _, tags = parse_wheel_filename(filename)
            if tags:
                # FIXME: This doesn't take into account precedence of
                # the supported tags for best fit.
                matching_tags = SUPPORTED_TAGS.intersection(tags)
                if not matching_tags:
                    if DEBUG_RESOLVER:
                        logger.debug(f"ignoring {filename} with tags {tags}")
                    continue
        except Exception as err:
            # Ignore files with invalid versions
            if DEBUG_RESOLVER:
                logger.debug(f'could not determine version for "{filename}": {err}')
            continue
        # Look for and ignore cases like `cffi-1.0.2-2.tar.gz` which
        # produces the name `cffi-1-0-2`. We can't just compare the
        # names directly because of case and punctuation changes in
        # making names canonical and the way requirements are
        # expressed and there seems to be *no* way of producing sdist
        # filenames consistently, so we compare the length for this
        # case.
        if len(name) != len(project):
            if DEBUG_RESOLVER:
                logger.debug(f'skipping invalid filename "{filename}"')
            continue

        c = Candidate(
            name, version, url=candidate_url, extras=extras, is_sdist=is_sdist
        )
        if DEBUG_RESOLVER:
            logger.debug("candidate %s (%s) %s", filename, c, candidate_url)
        yield c


def get_metadata_for_wheel(url: str) -> EmailMessage:
    data = requests.get(url).content
    with ZipFile(BytesIO(data)) as z:
        for n in z.namelist():
            if n.endswith(".dist-info/METADATA"):
                p = BytesParser()
                return p.parse(z.open(n), headersonly=True)

    # If we didn't find the metadata, return an empty dict
    return EmailMessage()


class PyPIProvider(ExtrasProvider):
    def __init__(
        self,
        include_sdists: bool = True,
        include_wheels: bool = True,
        sdist_server_url: str = "https://pypi.org/simple/",
    ):
        super().__init__()
        self.include_sdists = include_sdists
        self.include_wheels = include_wheels
        self.sdist_server_url = sdist_server_url

    def identify(self, requirement_or_candidate: Requirement | Candidate) -> str:
        return canonicalize_name(requirement_or_candidate.name)

    def get_extras_for(
        self,
        requirement_or_candidate: Requirement | Candidate,
    ) -> tuple[str]:
        # Extras is a set, which is not hashable
        return tuple(sorted(requirement_or_candidate.extras))

    def get_base_requirement(self, candidate: Candidate) -> Requirement:
        return Requirement(f"{candidate.name}=={candidate.version}")

    def get_preference(self, identifier, resolutions, candidates, information, **kwds):
        return sum(1 for _ in candidates[identifier])

    def find_matches(self, identifier, requirements, incompatibilities):
        requirements = list(requirements[identifier])
        bad_versions = {c.version for c in incompatibilities[identifier]}

        # Need to pass the extras to the search, so they
        # are added to the candidate at creation - we
        # treat candidates as immutable once created.
        candidates = []
        for candidate in get_project_from_pypi(
            identifier, set(), self.sdist_server_url
        ):
            # Skip versions that are known bad
            if candidate.version in bad_versions:
                continue
            # Skip versions that do not match the requirement
            if not all(candidate.version in r.specifier for r in requirements):
                continue
            # Only include sdists if we're asked to
            if self.include_sdists and not candidate.is_sdist:
                continue
            # Only include wheels if we're asked to
            if self.include_wheels and candidate.is_sdist:
                continue
            candidates.append(candidate)
        return sorted(candidates, key=attrgetter("version"), reverse=True)

    def is_satisfied_by(self, requirement: Requirement, candidate: Candidate) -> bool:
        if canonicalize_name(requirement.name) != candidate.name:
            return False
        return candidate.version in requirement.specifier

    def get_dependencies(self, candidate: Candidate) -> list:
        # return candidate.dependencies
        return []


class GitHubTagProvider(ExtrasProvider):
    def __init__(
        self,
        organization: str,
        repo: str,
    ):
        super().__init__()
        self.organization = organization
        self.repo = repo
        self.client = github.Github()

    def identify(self, requirement_or_candidate: Requirement | Candidate) -> str:
        return canonicalize_name(requirement_or_candidate.name)

    def get_extras_for(
        self, requirement_or_candidate: Requirement | Candidate
    ) -> tuple[str]:
        # Extras is a set, which is not hashable
        return tuple(sorted(requirement_or_candidate.extras))

    def get_base_requirement(self, candidate: Candidate) -> Requirement:
        return Requirement(f"{candidate.name}=={candidate.version}")

    def get_preference(self, identifier, resolutions, candidates, information, **kwds):
        return sum(1 for _ in candidates[identifier])

    def find_matches(self, identifier, requirements, incompatibilities):
        repo = self.client.get_repo(f"{self.organization}/{self.repo}")

        requirements = list(requirements[identifier])
        bad_versions = {c.version for c in incompatibilities[identifier]}

        # Need to pass the extras to the search, so they
        # are added to the candidate at creation - we
        # treat candidates as immutable once created.
        candidates = []
        for tag in repo.get_tags():
            try:
                version = Version(tag.name)
            except Exception as err:
                logger.debug(
                    f"could not parse version from git tag {tag.name} on {repo.full_name}: {err}"
                )
                continue
            # Skip versions that are known bad
            if version in bad_versions:
                continue
            # Skip versions that do not match the requirement
            if not all(version in r.specifier for r in requirements):
                continue
            candidates.append(Candidate(identifier, version, url=tag.name))
        return sorted(candidates, key=attrgetter("version"), reverse=True)

    def is_satisfied_by(self, requirement: Requirement, candidate: Candidate) -> bool:
        if canonicalize_name(requirement.name) != candidate.name:
            return False
        return candidate.version in requirement.specifier

    def get_dependencies(self, candidate: Candidate) -> list[Requirement]:
        # return candidate.dependencies
        return []
