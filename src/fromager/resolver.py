# Based on https://github.com/sarugaku/resolvelib/blob/main/examples/pypi_wheel_provider.py
#
# Modified to look at sdists instead of wheels and to avoid trying to
# resolve any dependencies.
#
import logging
import os
import typing
from operator import attrgetter
from platform import python_version
from urllib.parse import urljoin, urlparse

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

from .candidate import Candidate
from .constraints import Constraints
from .extras_provider import ExtrasProvider

logger = logging.getLogger(__name__)

PYTHON_VERSION = Version(python_version())
DEBUG_RESOLVER = os.environ.get("DEBUG_RESOLVER", "")
SUPPORTED_TAGS = set(sys_tags())


def get_project_from_pypi(
    project: str,
    extras: tuple[str],
    sdist_server_url: str,
) -> typing.Iterable[Candidate]:
    """Return candidates created from the project name and extras."""
    simple_index_url = sdist_server_url.rstrip("/") + "/" + project + "/"
    logger.debug("%s: getting available versions from %s", project, simple_index_url)
    data = requests.get(simple_index_url).content
    doc = html5lib.parse(data, namespaceHTMLElements=False)
    for i in doc.findall(".//a"):
        candidate_url = urljoin(simple_index_url, i.attrib["href"])
        py_req = i.attrib.get("data-requires-python")
        path = urlparse(candidate_url).path
        filename = path.rpartition("/")[-1]
        if DEBUG_RESOLVER:
            logger.debug("%s: candidate %r -> %r", project, candidate_url, filename)
        # Skip items that need a different Python version
        if py_req:
            try:
                spec = SpecifierSet(py_req)
            except InvalidSpecifier as err:
                # Ignore files with invalid python specifiers
                # e.g. shellingham has files with ">= '2.7'"
                if DEBUG_RESOLVER:
                    logger.debug(
                        f"{project}: skipping {filename} because of an invalid python version specifier {py_req}: {err}"
                    )
                continue
            if PYTHON_VERSION not in spec:
                if DEBUG_RESOLVER:
                    logger.debug(
                        f"{project}: skipping {filename} because of python version {py_req}"
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
                        logger.debug(f"{project}: ignoring {filename} with tags {tags}")
                    continue
        except Exception as err:
            # Ignore files with invalid versions
            if DEBUG_RESOLVER:
                logger.debug(
                    f'{project}: could not determine version for "{filename}": {err}'
                )
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
                logger.debug(f'{project}: skipping invalid filename "{filename}"')
            continue

        c = Candidate(
            name, version, url=candidate_url, extras=extras, is_sdist=is_sdist
        )
        if DEBUG_RESOLVER:
            logger.debug(
                "%s: candidate %s (%s) %s", project, filename, c, candidate_url
            )
        yield c


RequirementsMap: typing.TypeAlias = dict[str, typing.Iterable[Requirement]]
CandidatesMap: typing.TypeAlias = dict[str, typing.Iterable[Candidate]]
VersionSource: typing.TypeAlias = typing.Callable[
    [str, RequirementsMap, CandidatesMap],
    typing.Iterable[str | Version],
]


class BaseProvider(ExtrasProvider):
    def __init__(
        self,
        include_sdists: bool = True,
        include_wheels: bool = True,
        sdist_server_url: str = "https://pypi.org/simple/",
        constraints: Constraints | None = None,
    ):
        super().__init__()
        self.include_sdists = include_sdists
        self.include_wheels = include_wheels
        self.sdist_server_url = sdist_server_url
        self.constraints = constraints or Constraints({})

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

    def is_satisfied_by(self, requirement: Requirement, candidate: Candidate) -> bool:
        if canonicalize_name(requirement.name) != candidate.name:
            return False
        return (
            candidate.version in requirement.specifier
            and self.constraints.is_satisfied_by(requirement.name, candidate.version)
        )

    def get_dependencies(self, candidate: Candidate) -> list:
        # return candidate.dependencies
        return []

    def find_matches(
        self,
        identifier: str,
        requirements: RequirementsMap,
        incompatibilities: CandidatesMap,
    ) -> typing.Iterable[Version]:
        raise NotImplementedError()


class PyPIProvider(BaseProvider):
    def __init__(
        self,
        include_sdists: bool = True,
        include_wheels: bool = True,
        sdist_server_url: str = "https://pypi.org/simple/",
        constraints: Constraints | None = None,
    ):
        super().__init__()
        self.include_sdists = include_sdists
        self.include_wheels = include_wheels
        self.sdist_server_url = sdist_server_url
        self.constraints = constraints or Constraints({})

    def find_matches(
        self,
        identifier: str,
        requirements: RequirementsMap,
        incompatibilities: CandidatesMap,
    ) -> typing.Iterable[Version]:
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
                if DEBUG_RESOLVER:
                    logger.debug(
                        f"{identifier}: skipping bad version {candidate.version} from {bad_versions}"
                    )
                continue
            # Skip versions that do not match the requirement
            if not all(candidate.version in r.specifier for r in requirements):
                if DEBUG_RESOLVER:
                    logger.debug(
                        f"{identifier}: skipping {candidate.version} because it does not match {requirements}"
                    )
                continue
            # Skip versions that do not match the constraint
            if not self.constraints.is_satisfied_by(identifier, candidate.version):
                if DEBUG_RESOLVER:
                    c = self.constraints.get_constraint(identifier)
                    logger.debug(
                        f"{identifier}: skipping {candidate.version} due to constraint {c}"
                    )
                continue
            # Only include sdists if we're asked to
            if candidate.is_sdist and not self.include_sdists:
                if DEBUG_RESOLVER:
                    logger.debug(
                        f"{identifier}: skipping {candidate} because it is an sdist"
                    )
                continue
            # Only include wheels if we're asked to
            if not candidate.is_sdist and not self.include_wheels:
                if DEBUG_RESOLVER:
                    logger.debug(
                        f"{identifier}: skipping {candidate} because it is a wheel"
                    )
                continue
            candidates.append(candidate)
        return sorted(candidates, key=attrgetter("version"), reverse=True)


class GenericProvider(BaseProvider):
    def __init__(
        self,
        version_source: VersionSource,
        constraints: Constraints | None = None,
    ):
        super().__init__()
        self._version_source = version_source
        self.constraints = constraints or Constraints({})

    def find_matches(
        self,
        identifier: str,
        requirements: RequirementsMap,
        incompatibilities: CandidatesMap,
    ) -> typing.Iterable[Version]:
        requirements = list(requirements[identifier])
        bad_versions = {c.version for c in incompatibilities[identifier]}

        # Need to pass the extras to the search, so they
        # are added to the candidate at creation - we
        # treat candidates as immutable once created.
        candidates = []
        for item in self._version_source(identifier, requirements, incompatibilities):
            if isinstance(item, Version):
                version = item
            else:
                try:
                    version = Version(item)
                except Exception as err:
                    logger.debug(
                        f"{identifier}: could not parse version from {item}: {err}"
                    )
                    continue
            # Skip versions that are known bad
            if version in bad_versions:
                if DEBUG_RESOLVER:
                    logger.debug(
                        f"{identifier}: skipping bad version {version} from {bad_versions}"
                    )
                continue
            # Skip versions that do not match the requirement
            if not all(version in r.specifier for r in requirements):
                if DEBUG_RESOLVER:
                    logger.debug(
                        f"{identifier}: skipping {version} because it does not match {requirements}"
                    )
                continue
            # Skip versions that do not match the constraint
            if not self.constraints.is_satisfied_by(identifier, version):
                if DEBUG_RESOLVER:
                    c = self.constraints.get_constraint(identifier)
                    logger.debug(
                        f"{identifier}: skipping {version} due to constraint {c}"
                    )
                continue
            candidates.append(Candidate(identifier, version, url=item))
        return sorted(candidates, key=attrgetter("version"), reverse=True)


class GitHubTagProvider(GenericProvider):
    def __init__(
        self, organization: str, repo: str, constraints: Constraints | None = None
    ):
        self.organization = organization
        self.repo = repo
        token = os.getenv("GITHUB_TOKEN")
        auth = github.Auth.Token(token) if token else None
        self.client = github.Github(auth=auth)
        self.constraints = constraints or Constraints({})
        super().__init__(version_source=self._find_tags, constraints=constraints)

    def _find_tags(
        self,
        identifier: str,
        requirements: RequirementsMap,
        incompatibilities: CandidatesMap,
    ) -> typing.Iterable[Version]:
        repo = self.client.get_repo(f"{self.organization}/{self.repo}")

        for tag in repo.get_tags():
            try:
                version = Version(tag.name)
            except Exception as err:
                logger.debug(
                    f"{identifier}: could not parse version from git tag {tag.name} on {repo.full_name}: {err}"
                )
                continue
            yield version
