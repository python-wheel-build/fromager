# Based on https://github.com/sarugaku/resolvelib/blob/main/examples/pypi_wheel_provider.py
#
# Modified to look at sdists instead of wheels and to avoid trying to
# resolve any dependencies.
#
from __future__ import annotations

import logging
import os
import typing
from collections import defaultdict
from operator import attrgetter
from platform import python_version
from urllib.parse import urljoin, urlparse

import html5lib
import resolvelib
from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.tags import Tag, sys_tags
from packaging.utils import (
    BuildTag,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import Version
from resolvelib.resolvers import RequirementInformation

from . import overrides
from .candidate import Candidate
from .constraints import Constraints
from .extras_provider import ExtrasProvider
from .request_session import session
from .requirements_file import RequirementType

if typing.TYPE_CHECKING:
    from . import context

logger = logging.getLogger(__name__)

PYTHON_VERSION = Version(python_version())
DEBUG_RESOLVER = os.environ.get("DEBUG_RESOLVER", "")
SUPPORTED_TAGS = set(sys_tags())
PYPI_SERVER_URL = "https://pypi.org/simple"
GITHUB_URL = "https://github.com"


def resolve(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    sdist_server_url: str,
    include_sdists: bool = True,
    include_wheels: bool = True,
    req_type: RequirementType | None = None,
) -> tuple[str, Version]:
    # Create the (reusable) resolver.
    provider = overrides.find_and_invoke(
        req.name,
        "get_resolver_provider",
        default_resolver_provider,
        ctx=ctx,
        req=req,
        include_sdists=include_sdists,
        include_wheels=include_wheels,
        sdist_server_url=sdist_server_url,
        req_type=req_type,
    )
    return resolve_from_provider(provider, req)


def default_resolver_provider(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_server_url: str,
    include_sdists: bool,
    include_wheels: bool,
    req_type: RequirementType | None = None,
) -> PyPIProvider | GenericProvider | GitHubTagProvider:
    """Lookup resolver provider to resolve package versions"""
    return PyPIProvider(
        include_sdists=include_sdists,
        include_wheels=include_wheels,
        sdist_server_url=sdist_server_url,
        constraints=ctx.constraints,
        req_type=req_type,
    )


def resolve_from_provider(
    provider: BaseProvider, req: Requirement
) -> tuple[str, Version]:
    reporter: resolvelib.BaseReporter = resolvelib.BaseReporter()
    rslvr: resolvelib.Resolver = resolvelib.Resolver(provider, reporter)
    try:
        result = rslvr.resolve([req])
    except resolvelib.resolvers.exceptions.ResolutionImpossible as err:
        raise ValueError(f"Unable to resolve {req}") from err
    # resolvelib actually just returns one candidate per requirement.
    # result.mapping is map from an identifier to its resolved candidate
    candidate: Candidate
    for candidate in result.mapping.values():
        return candidate.url, candidate.version
    raise ValueError(f"Unable to resolve {req}")


def get_project_from_pypi(
    project: str,
    extras: typing.Iterable[str],
    sdist_server_url: str,
) -> typing.Iterable[Candidate]:
    """Return candidates created from the project name and extras."""
    simple_index_url = sdist_server_url.rstrip("/") + "/" + project + "/"
    logger.debug("%s: getting available versions from %s", project, simple_index_url)
    data = session.get(simple_index_url).content
    doc = html5lib.parse(data, namespaceHTMLElements=False)
    for i in doc.findall(".//a"):
        candidate_url = urljoin(simple_index_url, i.attrib["href"])
        py_req = i.attrib.get("data-requires-python")
        path = urlparse(candidate_url).path
        filename = path.rsplit("/", 1)[-1]
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
                tags: frozenset[Tag] = frozenset()
                build_tag: BuildTag = ()
            else:
                is_sdist = False
                name, version, build_tag, tags = parse_wheel_filename(filename)
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
            name,
            version,
            url=candidate_url,
            extras=extras,
            is_sdist=is_sdist,
            build_tag=build_tag,
        )
        if DEBUG_RESOLVER:
            logger.debug(
                "%s: candidate %s (%s) %s", project, filename, c, candidate_url
            )
        yield c


RequirementsMap: typing.TypeAlias = typing.Mapping[str, typing.Iterable[Requirement]]
CandidatesMap: typing.TypeAlias = typing.Mapping[str, typing.Iterable[Candidate]]
VersionSource: typing.TypeAlias = typing.Callable[
    [str, RequirementsMap, CandidatesMap],
    typing.Iterable[tuple[str, str | Version]],
]


class BaseProvider(ExtrasProvider):
    def __init__(
        self,
        include_sdists: bool = True,
        include_wheels: bool = True,
        sdist_server_url: str = "https://pypi.org/simple/",
        constraints: Constraints | None = None,
        req_type: RequirementType | None = None,
    ):
        super().__init__()
        self.include_sdists = include_sdists
        self.include_wheels = include_wheels
        self.sdist_server_url = sdist_server_url
        self.constraints = constraints or Constraints({})
        self.req_type = req_type

    def identify(self, requirement_or_candidate: Requirement | Candidate) -> str:
        return canonicalize_name(requirement_or_candidate.name)

    def get_extras_for(
        self,
        requirement_or_candidate: Requirement | Candidate,
    ) -> typing.Iterable[str]:
        # Extras is a set, which is not hashable
        if requirement_or_candidate.extras:
            return tuple(sorted(requirement_or_candidate.extras))
        return tuple()

    def get_base_requirement(self, candidate: Candidate) -> Requirement:
        return Requirement(f"{candidate.name}=={candidate.version}")

    def validate_candidate(
        self,
        identifier: str,
        requirements: RequirementsMap,
        incompatibilities: CandidatesMap,
        candidate: Candidate,
    ) -> bool:
        identifier_reqs = list(requirements[identifier])
        bad_versions = {c.version for c in incompatibilities[identifier]}
        allow_prerelease = self.constraints.allow_prerelease(identifier)

        # Skip versions that are known bad
        if candidate.version in bad_versions:
            if DEBUG_RESOLVER:
                logger.debug(
                    f"{identifier}: skipping bad version {candidate.version} from {bad_versions}"
                )
            return False
        # Skip versions that do not match the requirement. Allow prereleases only if constraints allow prereleases
        if not all(
            r.specifier.contains(
                candidate.version,
                prereleases=(allow_prerelease or bool(r.specifier.prereleases)),
            )
            for r in identifier_reqs
        ):
            if DEBUG_RESOLVER:
                logger.debug(
                    f"{identifier}: skipping {candidate.version} because it does not match {identifier_reqs}"
                )
            return False
        # Skip versions that do not match the constraint
        if not self.constraints.is_satisfied_by(identifier, candidate.version):
            if DEBUG_RESOLVER:
                c = self.constraints.get_constraint(identifier)
                logger.debug(
                    f"{identifier}: skipping {candidate.version} due to constraint {c}"
                )
            return False
        return True

    def get_cache(self) -> dict[str, list[Candidate]]:
        raise NotImplementedError()

    def get_from_cache(
        self,
        identifier: str,
        requirements: RequirementsMap,
        incompatibilities: CandidatesMap,
    ) -> list[Candidate]:
        cache = self.get_cache()
        # we only want caching for build reqs because for install time reqs we always want to get the latest version
        # we can't guarantee that the latest version is available in the cache so install time reqs cannot use the cache
        if self.req_type != RequirementType.BUILD:
            return []
        return [
            c
            for c in cache[identifier]
            if self.validate_candidate(identifier, requirements, incompatibilities, c)
        ]

    def add_to_cache(self, identifier: str, candidates: list[Candidate]) -> None:
        # we can add candidates to cache even for install type reqs because build time reqs are
        # allowed to use candidates seen when we were resolving the same req as an install type
        self.get_cache()[identifier].extend(candidates)

    def get_preference(
        self,
        identifier: str,
        resolutions: typing.Mapping[str, Candidate],
        candidates: CandidatesMap,
        information: typing.Mapping[
            str, typing.Iterable[RequirementInformation[Requirement, Candidate]]
        ],
        backtrack_causes: typing.Sequence[
            RequirementInformation[Requirement, Candidate]
        ],
    ) -> int:
        return sum(1 for _ in candidates[identifier])

    def is_satisfied_by(self, requirement: Requirement, candidate: Candidate) -> bool:
        if canonicalize_name(requirement.name) != candidate.name:
            return False
        allow_prerelease = self.constraints.allow_prerelease(requirement.name) or bool(
            requirement.specifier.prereleases
        )
        return requirement.specifier.contains(
            candidate.version, prereleases=allow_prerelease
        ) and self.constraints.is_satisfied_by(requirement.name, candidate.version)

    def get_dependencies(self, candidate: Candidate) -> list[Requirement]:
        # return candidate.dependencies
        return []

    def find_matches(
        self,
        identifier: str,
        requirements: RequirementsMap,
        incompatibilities: CandidatesMap,
    ) -> typing.Iterable[Candidate]:
        raise NotImplementedError()


class PyPIProvider(BaseProvider):
    """Lookup package and versions from a simple Python index (PyPI)"""

    pypi_resolver_cache: typing.ClassVar[dict[str, list[Candidate]]] = defaultdict(list)

    def __init__(
        self,
        include_sdists: bool = True,
        include_wheels: bool = True,
        sdist_server_url: str = "https://pypi.org/simple/",
        constraints: Constraints | None = None,
        req_type: RequirementType | None = None,
    ):
        super().__init__(
            include_sdists=include_sdists,
            include_wheels=include_wheels,
            sdist_server_url=sdist_server_url,
            constraints=constraints,
            req_type=req_type,
        )

    def get_cache(self) -> dict[str, list[Candidate]]:
        return PyPIProvider.pypi_resolver_cache

    def validate_candidate(
        self,
        identifier: str,
        requirements: RequirementsMap,
        incompatibilities: CandidatesMap,
        candidate: Candidate,
    ) -> bool:
        if not super().validate_candidate(
            identifier, requirements, incompatibilities, candidate
        ):
            return False
        # Only include sdists if we're asked to
        if candidate.is_sdist and not self.include_sdists:
            if DEBUG_RESOLVER:
                logger.debug(
                    f"{identifier}: skipping {candidate} because it is an sdist"
                )
            return False
        # Only include wheels if we're asked to
        if not candidate.is_sdist and not self.include_wheels:
            if DEBUG_RESOLVER:
                logger.debug(
                    f"{identifier}: skipping {candidate} because it is a wheel"
                )
            return False
        return True

    def find_matches(
        self,
        identifier: str,
        requirements: RequirementsMap,
        incompatibilities: CandidatesMap,
    ) -> typing.Iterable[Candidate]:
        candidates = self.get_from_cache(identifier, requirements, incompatibilities)
        if not candidates:
            # Need to pass the extras to the search, so they
            # are added to the candidate at creation - we
            # treat candidates as immutable once created.
            for candidate in get_project_from_pypi(
                identifier, set(), self.sdist_server_url
            ):
                if self.validate_candidate(
                    identifier, requirements, incompatibilities, candidate
                ):
                    candidates.append(candidate)
            self.add_to_cache(identifier, candidates)
        return sorted(candidates, key=attrgetter("version", "build_tag"), reverse=True)


class GenericProvider(BaseProvider):
    """Lookup package and version by using a callback"""

    generic_resolver_cache: typing.ClassVar[dict[str, list[Candidate]]] = defaultdict(
        list
    )

    def __init__(
        self,
        version_source: VersionSource,
        constraints: Constraints | None = None,
        req_type: RequirementType | None = None,
    ):
        super().__init__(constraints=constraints, req_type=req_type)
        self._version_source = version_source

    def get_cache(self) -> dict[str, list[Candidate]]:
        return GenericProvider.generic_resolver_cache

    def find_matches(
        self,
        identifier: str,
        requirements: RequirementsMap,
        incompatibilities: CandidatesMap,
    ) -> typing.Iterable[Candidate]:
        candidates = self.get_from_cache(identifier, requirements, incompatibilities)

        if not candidates:
            # Need to pass the extras to the search, so they
            # are added to the candidate at creation - we
            # treat candidates as immutable once created.
            for url, item in self._version_source(
                identifier, requirements, incompatibilities
            ):
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
                candidate = Candidate(identifier, version, url=url)
                if self.validate_candidate(
                    identifier, requirements, incompatibilities, candidate
                ):
                    candidates.append(candidate)
                self.add_to_cache(identifier, candidates)

        return sorted(candidates, key=attrgetter("version"), reverse=True)


class GitHubTagProvider(GenericProvider):
    """Lookup tarball and version from GitHub git tags

    Assumes that upstream uses version tags `1.2.3` or `v1.2.3`.
    """

    host = "github.com:443"
    api_url = "https://api.{self.host}/repos/{self.organization}/{self.repo}/tags"
    github_resolver_cache: typing.ClassVar[dict[str, list[Candidate]]] = defaultdict(
        list
    )

    def __init__(
        self, organization: str, repo: str, constraints: Constraints | None = None
    ):
        super().__init__(version_source=self._find_tags, constraints=constraints)
        self.organization = organization
        self.repo = repo

    def get_cache(self) -> dict[str, list[Candidate]]:
        return GitHubTagProvider.github_resolver_cache

    def _find_tags(
        self,
        identifier: str,
        requirements: RequirementsMap,
        incompatibilities: CandidatesMap,
    ) -> typing.Iterable[tuple[str, Version]]:
        headers = {"accept": "application/vnd.github+json"}
        nexturl = self.api_url.format(self=self)
        while nexturl:
            resp = session.get(nexturl, headers=headers)
            resp.raise_for_status()
            for entry in resp.json():
                name = entry["name"]
                try:
                    version = Version(name)
                except Exception as err:
                    logger.debug(
                        f"{identifier}: could not parse version from {name}: {err}"
                    )
                    continue

                yield entry["tarball_url"], version
            # pagination links
            nexturl = resp.links.get("next", {}).get("url")
