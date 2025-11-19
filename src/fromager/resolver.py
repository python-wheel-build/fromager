# Based on https://github.com/sarugaku/resolvelib/blob/main/examples/pypi_wheel_provider.py
#
# Modified to look at sdists instead of wheels and to avoid trying to
# resolve any dependencies.
#
from __future__ import annotations

import datetime
import functools
import logging
import os
import re
import typing
from collections.abc import Iterable
from operator import attrgetter
from platform import python_version
from urllib.parse import quote, unquote, urljoin, urlparse

import pypi_simple
import resolvelib
from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.tags import Tag, sys_tags
from packaging.utils import (
    BuildTag,
    canonicalize_name,
    parse_wheel_filename,
)
from packaging.version import Version
from requests.models import Response
from resolvelib.resolvers import RequirementInformation

from . import overrides
from .candidate import Candidate
from .constraints import Constraints
from .extras_provider import ExtrasProvider
from .http_retry import RETRYABLE_EXCEPTIONS, retry_on_exception
from .request_session import session
from .requirements_file import RequirementType

if typing.TYPE_CHECKING:
    from . import context


logger = logging.getLogger(__name__)

PYTHON_VERSION = Version(python_version())
DEBUG_RESOLVER = os.environ.get("DEBUG_RESOLVER", "")
PYPI_SERVER_URL = "https://pypi.org/simple"
GITHUB_URL = "https://github.com"

# all supported tags
SUPPORTED_TAGS: frozenset[Tag] = frozenset(sys_tags())
# same, but ignore the platform for 'ignore_platform' flag
IGNORE_PLATFORM: str = "ignore"
SUPPORTED_TAGS_IGNORE_PLATFORM: frozenset[Tag] = frozenset(
    Tag(t.interpreter, t.abi, IGNORE_PLATFORM) for t in SUPPORTED_TAGS
)


@functools.lru_cache(maxsize=200)
def match_py_req(py_req: str, *, python_version: Version = PYTHON_VERSION) -> bool:
    """Python version requirement lookup with LRU cache

    Raises InvalidSpecifier on error

    SpecifierSet parsing and matching takes a non-trivial amount of time. A
    bootstrap run can spend over 10% of its time in parsing and matching
    Python version requirements.

    This function caches the result of SpecifierSet parsing and contains
    operation for Python version requirement. Most packages share similar
    constraints, e.g. ``>= 3.10``.
    """
    return python_version in SpecifierSet(py_req)


def resolve(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    sdist_server_url: str,
    include_sdists: bool = True,
    include_wheels: bool = True,
    req_type: RequirementType | None = None,
    ignore_platform: bool = False,
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
        ignore_platform=ignore_platform,
    )
    return resolve_from_provider(provider, req)


def default_resolver_provider(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_server_url: str,
    include_sdists: bool,
    include_wheels: bool,
    req_type: RequirementType | None = None,
    ignore_platform: bool = False,
) -> PyPIProvider | GenericProvider | GitHubTagProvider:
    """Lookup resolver provider to resolve package versions"""
    return PyPIProvider(
        include_sdists=include_sdists,
        include_wheels=include_wheels,
        sdist_server_url=sdist_server_url,
        constraints=ctx.constraints,
        req_type=req_type,
        ignore_platform=ignore_platform,
    )


def extract_filename_from_url(url: str) -> str:
    """Extract filename from URL and decode it."""
    path = urlparse(url).path
    filename = os.path.basename(path)
    return unquote(filename)


class LogReporter(resolvelib.BaseReporter):
    """Report resolution events

    Implements part of the BaseReporter API to log a few events related to
    resolving requirements.

    """

    def __init__(self, req: Requirement):
        self.req = req
        super().__init__()

    def _report(self, msg: str, *args: typing.Any) -> None:
        logger.info(msg, *args)

    def starting(self) -> None:
        self._report("looking for candidates for %r", self.req)

    def rejecting_candidate(self, criterion, candidate):
        self._report("resolver rejecting candidate %s: %s", candidate, criterion)

    def pinning(self, candidate):
        self._report("selecting %s", candidate)

    def ending(self, state):
        self._report("successfully resolved %r", self.req)


def resolve_from_provider(
    provider: BaseProvider, req: Requirement
) -> tuple[str, Version]:
    reporter = LogReporter(req)
    rslvr: resolvelib.Resolver = resolvelib.Resolver(provider, reporter)
    try:
        result = rslvr.resolve([req])
    except resolvelib.resolvers.ResolverException as err:
        constraint = provider.constraints.get_constraint(req.name)
        provider_desc = provider.get_provider_description()
        # Include the original error message to preserve detailed information
        # (e.g., file types, pre-release info from PyPIProvider)
        original_msg = str(err)
        raise resolvelib.resolvers.ResolverException(
            f"Unable to resolve requirement specifier {req} with constraint {constraint} using {provider_desc}: {original_msg}"
        ) from err
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
    ignore_platform: bool = False,
) -> Candidates:
    """Return candidates created from the project name and extras."""
    found_candidates: set[str] = set()
    ignored_candidates: set[str] = set()
    logger.debug("%s: getting available versions from %s", project, sdist_server_url)

    client = pypi_simple.PyPISimple(
        endpoint=sdist_server_url,
        session=session,
        accept=pypi_simple.ACCEPT_JSON_PREFERRED,
    )
    try:
        package = client.get_project_page(project)
    except Exception as e:
        logger.debug(
            "failed to fetch package index from %s: %s",
            sdist_server_url,
            e,
        )
        raise

    # PEP 792 package status
    match package.status:
        case None:
            logger.debug("no package status")
        case pypi_simple.ProjectStatus.ACTIVE:
            logger.debug("project %r is active: %s", project, package.status_reason)
        case pypi_simple.ProjectStatus.DEPRECATED | pypi_simple.ProjectStatus.ARCHIVED:
            logger.warning(
                "project %r is no longer active: %r: %s",
                project,
                package.status,
                package.status_reason,
            )
        case pypi_simple.ProjectStatus.QUARANTINED:
            raise ValueError(
                f"project {project!r} is quarantined: {package.status_reason}"
            )
        case _:
            logger.warning(
                "project %r has unknown status %r: %s",
                project,
                package.status,
                package.status_reason,
            )

    for dp in package.packages:
        found_candidates.add(dp.filename)
        if DEBUG_RESOLVER:
            logger.debug("candidate %r -> %r==%r", dp.url, dp.filename, dp.version)

        if (
            dp.project is None
            or dp.version is None
            or dp.package_type is None
            or len(dp.project) != len(project)
        ):
            # Legacy file names that pypi_simple does not understand,
            # pypi_simple sets one or all fields to None.
            #
            # Look for and ignore cases like `cffi-1.0.2-2.tar.gz` which
            # produces the name `cffi-1-0-2`. We can't just compare the
            # names directly because of case and punctuation changes in
            # making names canonical and the way requirements are
            # expressed and there seems to be *no* way of producing sdist
            # filenames consistently, so we compare the length for this
            # case.
            if DEBUG_RESOLVER:
                logger.debug(
                    "skipping %r because 'pypi_simple' could not parse it or it's an invalid name",
                    dp.filename,
                )
            ignored_candidates.add(dp.filename)
            continue

        if dp.package_type not in {"sdist", "wheel"}:
            if DEBUG_RESOLVER:
                logger.debug(
                    "skipping %r because it's not an sdist or wheel, got %r",
                    dp.filename,
                    dp.package_type,
                )
            ignored_candidates.add(dp.filename)
            continue

        # PEP 592: Skip items that were yanked
        if dp.is_yanked:
            if DEBUG_RESOLVER:
                logger.debug(
                    "skipping %s because it was yanked (%s)",
                    dp.filename,
                    dp.yanked_reason,
                )
            ignored_candidates.add(dp.filename)
            continue

        # Skip items that need a different Python version
        if dp.requires_python:
            try:
                matched_py: bool = match_py_req(dp.requires_python)
            except InvalidSpecifier as err:
                # Ignore files with invalid python specifiers
                # e.g. shellingham has files with ">= '2.7'"
                if DEBUG_RESOLVER:
                    logger.debug(
                        "skipping %r because of an invalid python version specifier %r: %s",
                        dp.filename,
                        dp.requires_python,
                        err,
                    )
                ignored_candidates.add(dp.filename)
                continue
            if not matched_py:
                if DEBUG_RESOLVER:
                    logger.debug(
                        "skipping %r because of python version %r",
                        dp.filename,
                        dp.requires_python,
                    )
                ignored_candidates.add(dp.filename)
                continue

        # TODO: Handle compatibility tags?

        try:
            if dp.package_type == "sdist":
                is_sdist = True
                name: str = dp.project
                version: Version = Version(dp.version)
                tags: frozenset[Tag] = frozenset()
                build_tag: BuildTag = ()
            else:
                is_sdist = False
                name, version, build_tag, tags = parse_wheel_filename(dp.filename)
        except Exception as err:
            # Ignore files with invalid versions
            if DEBUG_RESOLVER:
                logger.debug("could not determine version for %r: %s", dp.filename, err)
            ignored_candidates.add(dp.filename)
            continue

        if tags:
            # FIXME: This doesn't take into account precedence of
            # the supported tags for best fit.
            matching_tags = SUPPORTED_TAGS.intersection(tags)
            if not matching_tags and ignore_platform:
                if DEBUG_RESOLVER:
                    logger.debug("ignoring platform for %r", dp.filename)
                ignore_platform_tags: frozenset[Tag] = frozenset(
                    Tag(t.interpreter, t.abi, IGNORE_PLATFORM) for t in tags
                )
                matching_tags = SUPPORTED_TAGS_IGNORE_PLATFORM.intersection(
                    ignore_platform_tags
                )
            if not matching_tags:
                if DEBUG_RESOLVER:
                    logger.debug("ignoring %r with tags %r", dp.filename, tags)
                ignored_candidates.add(dp.filename)
                continue

        upload_time = dp.upload_time
        if upload_time is not None:
            upload_time = upload_time.astimezone(datetime.UTC)

        c = Candidate(
            name=name,
            version=version,
            url=dp.url,
            extras=tuple(sorted(extras)),
            is_sdist=is_sdist,
            build_tag=build_tag,
            has_metadata=bool(dp.has_metadata),
            upload_time=upload_time,
        )
        if DEBUG_RESOLVER:
            logger.debug("candidate %s (%s) %s", dp.filename, c, dp.url)
        yield c

    if not found_candidates:
        logger.info("found no candidate files at %s", sdist_server_url)
    elif ignored_candidates == found_candidates:
        logger.info("ignored all candidate files at %s", sdist_server_url)


RequirementsMap: typing.TypeAlias = typing.Mapping[str, typing.Iterable[Requirement]]
Candidates: typing.TypeAlias = typing.Iterable[Candidate]
CandidatesMap: typing.TypeAlias = typing.Mapping[str, Candidates]
# {identifier: [cls, cachekey]: list[candidates]}}
ResolverCache: typing.TypeAlias = dict[
    str, dict[tuple[type[ExtrasProvider], str], list[Candidate]]
]
VersionSource: typing.TypeAlias = typing.Callable[
    [str],
    typing.Iterable[Candidate | tuple[str, str | Version]],
]


class BaseProvider(ExtrasProvider):
    resolver_cache: typing.ClassVar[ResolverCache] = {}
    provider_description: typing.ClassVar[str]

    def __init__(
        self,
        *,
        constraints: Constraints | None = None,
        req_type: RequirementType | None = None,
        use_resolver_cache: bool = True,
    ):
        super().__init__()
        self.constraints = constraints or Constraints()
        self.req_type = req_type
        self.use_cache_candidates = use_resolver_cache

    @property
    def cache_key(self) -> str:
        """Return cache key for the provider

        The cache key must be unique for each provider configuration, e.g.
        PyPI URL, GitHub org + repo, ...
        """
        raise NotImplementedError()

    def get_provider_description(self) -> str:
        """Return a human-readable description of the provider type

        This is used in error messages to indicate what resolver was being used.
        The ClassVar `provider_description` must be set by each subclass.
        If it contains format placeholders like {self.attr}, it will be formatted
        with the instance. Strings without placeholders are returned unchanged.
        """
        return self.provider_description.format(self=self)

    def find_candidates(self, identifier: str) -> Candidates:
        """Find unfiltered candidates"""
        raise NotImplementedError()

    def identify(self, requirement_or_candidate: Requirement | Candidate) -> str:
        return canonicalize_name(requirement_or_candidate.name)

    @classmethod
    def clear_cache(cls, identifier: str | None = None) -> None:
        """Clear global resolver cache

        ``None`` clears all caches, an ``identifier`` string clears the
        cache for an identifier. Raises :exc:`KeyError` for unknown
        identifiers.
        """
        if identifier is None:
            cls.resolver_cache.clear()
        else:
            cls.resolver_cache.pop(canonicalize_name(identifier))

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
        # Skip versions that are known bad
        if candidate.version in bad_versions:
            if DEBUG_RESOLVER:
                logger.debug(
                    f"{identifier}: skipping bad version {candidate.version} from {bad_versions}"
                )
            return False
        for r in identifier_reqs:
            if self.is_satisfied_by(requirement=r, candidate=candidate):
                return True
        return False

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
        if not requirement.specifier.contains(
            candidate.version, prereleases=allow_prerelease
        ):
            if DEBUG_RESOLVER:
                logger.debug(
                    f"{requirement.name}: skipping candidate version {candidate.version} because it does not match {requirement.specifier}"
                )
            return False

        if not self.constraints.is_satisfied_by(requirement.name, candidate.version):
            if DEBUG_RESOLVER:
                c = self.constraints.get_constraint(requirement.name)
                logger.debug(
                    f"{requirement.name}: skipping {candidate.version} due to constraint {c}"
                )
            return False

        return True

    def get_dependencies(self, candidate: Candidate) -> list[Requirement]:
        # return candidate.dependencies
        return []

    def _get_cached_candidates(self, identifier: str) -> list[Candidate]:
        """Get list of cached candidates for identifier and provider

        The method always returns a list. If the cache did not have an entry
        before, a new empty list is stored in the cache and returned to the
        caller. The caller can mutate the list in place to update the cache.
        """
        cls = type(self)
        provider_cache = cls.resolver_cache.setdefault(identifier, {})
        candidate_cache = provider_cache.setdefault((cls, self.cache_key), [])
        return candidate_cache

    def _find_cached_candidates(self, identifier: str) -> Candidates:
        """Find candidates with caching"""
        cached_candidates: list[Candidate] = []
        if self.use_cache_candidates:
            cached_candidates = self._get_cached_candidates(identifier)
            if cached_candidates:
                logger.debug(
                    "%s: use %i cached candidates",
                    identifier,
                    len(cached_candidates),
                )
                return cached_candidates
        candidates = list(self.find_candidates(identifier))
        if self.use_cache_candidates:
            # mutate list object in-place
            cached_candidates[:] = candidates
            logger.debug(
                "%s: cache %i unfiltered candidates",
                identifier,
                len(candidates),
            )
        else:
            logger.debug(
                "%s: got %i unfiltered candidates, ignoring cache",
                identifier,
                len(candidates),
            )
        return candidates

    def _get_no_match_error_message(
        self, identifier: str, requirements: RequirementsMap
    ) -> str:
        """Generate an error message when no candidates are found.

        Subclasses should override this to provide provider-specific error details.
        """
        r = next(iter(requirements[identifier]))
        return f"found no match for {r} using {self.get_provider_description()}"

    def find_matches(
        self,
        identifier: str,
        requirements: RequirementsMap,
        incompatibilities: CandidatesMap,
    ) -> Candidates:
        """Find matching candidates, sorted by version and build tag"""
        unfiltered_candidates = self._find_cached_candidates(identifier)
        candidates = [
            candidate
            for candidate in unfiltered_candidates
            if self.validate_candidate(
                identifier, requirements, incompatibilities, candidate
            )
        ]
        if not candidates:
            raise resolvelib.resolvers.ResolverException(
                self._get_no_match_error_message(identifier, requirements)
            )
        return sorted(candidates, key=attrgetter("version", "build_tag"), reverse=True)


class PyPIProvider(BaseProvider):
    """Lookup package and versions from a simple Python index (PyPI)"""

    provider_description: typing.ClassVar[str] = (
        "PyPI resolver (searching at {self.sdist_server_url})"
    )

    def __init__(
        self,
        include_sdists: bool = True,
        include_wheels: bool = True,
        sdist_server_url: str = "https://pypi.org/simple/",
        constraints: Constraints | None = None,
        req_type: RequirementType | None = None,
        ignore_platform: bool = False,
        *,
        use_resolver_cache: bool = True,
    ):
        super().__init__(
            constraints=constraints,
            req_type=req_type,
            use_resolver_cache=use_resolver_cache,
        )
        self.include_sdists = include_sdists
        self.include_wheels = include_wheels
        self.sdist_server_url = sdist_server_url
        self.ignore_platform = ignore_platform

    @property
    def cache_key(self) -> str:
        # ignore platform parameter changes behavior of find_candidates()
        if self.ignore_platform:
            return f"{self.sdist_server_url}+ignore_platform"
        else:
            return self.sdist_server_url

    def find_candidates(self, identifier: str) -> Candidates:
        return get_project_from_pypi(
            identifier,
            set(),
            self.sdist_server_url,
            self.ignore_platform,
        )

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

    def _get_no_match_error_message(
        self, identifier: str, requirements: RequirementsMap
    ) -> str:
        """Generate a PyPI-specific error message with file type and pre-release details."""
        r = next(iter(requirements[identifier]))

        # Determine if pre-releases are allowed
        req_allows_prerelease = bool(r.specifier) and bool(r.specifier.prereleases)
        allow_prerelease = (
            self.constraints.allow_prerelease(r.name) or req_allows_prerelease
        )
        prerelease_info = "including" if allow_prerelease else "ignoring"

        # Determine the file type that was allowed
        if self.include_sdists and self.include_wheels:
            file_type_info = "any file type"
        elif self.include_sdists:
            file_type_info = "sdists"
        else:
            file_type_info = "wheels"

        return (
            f"found no match for {r} using {self.get_provider_description()}, "
            f"searching for {file_type_info}, {prerelease_info} pre-release versions"
        )

    def find_matches(
        self,
        identifier: str,
        requirements: RequirementsMap,
        incompatibilities: CandidatesMap,
    ) -> Candidates:
        return super().find_matches(identifier, requirements, incompatibilities)


class MatchFunction(typing.Protocol):
    def __call__(self, identifier: str, item: str) -> Version | None:
        pass


class GenericProvider(BaseProvider):
    """Lookup package and version by using a callback"""

    def __init__(
        self,
        version_source: VersionSource,
        constraints: Constraints | None = None,
        req_type: RequirementType | None = None,
        matcher: MatchFunction | re.Pattern | None = None,
        *,
        # generic provider does not implement caching
        use_resolver_cache: bool = False,
    ):
        super().__init__(
            constraints=constraints,
            req_type=req_type,
            use_resolver_cache=use_resolver_cache,
        )
        self._version_source = version_source
        if matcher is None:
            self._match_function = self._default_match_function
        elif isinstance(matcher, re.Pattern):
            self._match_function = functools.partial(
                self._re_match_function, regex=matcher
            )
        else:
            self._match_function = matcher

    def _default_match_function(self, identifier: str, item: str) -> Version | None:
        try:
            return Version(item)
        except Exception as err:
            logger.debug(f"{identifier}: could not parse version from {item}: {err}")
            return None

    def _re_match_function(
        self, identifier: str, item: str, *, regex: re.Pattern
    ) -> Version | None:
        mo = regex.match(item)
        if mo is None:
            logger.debug(
                f"{identifier}: tag {item} does not match pattern {regex.pattern}"
            )
            return None
        value = mo.group(1)
        try:
            return Version(value)
        except Exception as err:
            logger.debug(f"{identifier}: could not parse version from {value}: {err}")
            return None

    provider_description: typing.ClassVar[str] = "custom resolver (GenericProvider)"

    @property
    def cache_key(self) -> str:
        raise NotImplementedError("GenericProvider does not implement caching")

    def find_candidates(self, identifier) -> Candidates:
        candidates: list[Candidate] = []
        version: Version | None
        for item in self._version_source(identifier):
            if isinstance(item, Candidate):
                candidate = item
            else:
                # TODO: deprecate (url, version_or_string)
                url, version_or_string = item
                if isinstance(version_or_string, Version):
                    version = version_or_string
                else:
                    match_result = self._match_function(identifier, version_or_string)
                    if match_result is None:
                        logger.debug(
                            f"{identifier}: match function ignores {version_or_string}"
                        )
                        continue
                    assert isinstance(match_result, Version)
                    version = match_result

                candidate = Candidate(name=identifier, version=version, url=url)

            candidates.append(candidate)

        return candidates


class GitHubTagProvider(GenericProvider):
    """Lookup tarball and version from GitHub git tags

    Assumes that upstream uses version tags `1.2.3` or `v1.2.3`.
    """

    provider_description: typing.ClassVar[str] = (
        "GitHub tag resolver (repository: {self.organization}/{self.repo})"
    )
    host = "github.com:443"
    api_url = "https://api.{self.host}/repos/{self.organization}/{self.repo}/tags"

    def __init__(
        self,
        organization: str,
        repo: str,
        constraints: Constraints | None = None,
        matcher: MatchFunction | re.Pattern | None = None,
        *,
        req_type: RequirementType | None = None,
        use_resolver_cache: bool = True,
    ):
        super().__init__(
            constraints=constraints,
            req_type=req_type,
            use_resolver_cache=use_resolver_cache,
            version_source=self._find_tags,
            matcher=matcher,
        )
        self.organization = organization
        self.repo = repo

    @property
    def cache_key(self) -> str:
        return f"{self.organization}/{self.repo}"

    @retry_on_exception(
        exceptions=RETRYABLE_EXCEPTIONS,
        max_attempts=5,
        backoff_factor=1.5,
        max_backoff=120.0,
    )
    def _find_tags(
        self,
        identifier: str,
    ) -> Iterable[Candidate]:
        headers = {"accept": "application/vnd.github+json"}

        # Add GitHub authentication if available
        github_token = os.environ.get("GITHUB_TOKEN")
        if github_token:
            headers["Authorization"] = f"token {github_token}"

        nexturl = self.api_url.format(self=self)
        while nexturl:
            resp = session.get(nexturl, headers=headers)
            resp.raise_for_status()

            for entry in resp.json():
                tagname = entry["name"]
                version = self._match_function(identifier, tagname)
                if version is None:
                    logger.debug(f"{identifier}: match function ignores {tagname}")
                    continue
                assert isinstance(version, Version)
                url = entry["tarball_url"]

                # Github tag API endpoint does not include commit date information.
                # It would be too expensive to query every commit API endpoint.
                yield Candidate(
                    name=identifier,
                    version=version,
                    url=url,
                    remote_tag=tagname,
                    remote_commit=entry["commit"]["sha"],
                    upload_time=None,
                )

            # pagination links
            nexturl = resp.links.get("next", {}).get("url")


class GitLabTagProvider(GenericProvider):
    """Lookup tarball and version from GitLab git tags"""

    provider_description: typing.ClassVar[str] = (
        "GitLab tag resolver (project: {self.server_url}/{self.project_path})"
    )

    def __init__(
        self,
        project_path: str,
        server_url: str = "https://gitlab.com",
        constraints: Constraints | None = None,
        matcher: MatchFunction | re.Pattern | None = None,
        *,
        req_type: RequirementType | None = None,
        use_resolver_cache: bool = True,
    ) -> None:
        super().__init__(
            constraints=constraints,
            req_type=req_type,
            use_resolver_cache=use_resolver_cache,
            version_source=self._find_tags,
            matcher=matcher,
        )
        self.server_url = server_url.rstrip("/")
        self.project_path = project_path.lstrip("/")
        # URL-encode the project path as required by GitLab API.
        # The safe="" parameter tells quote() to encode ALL characters,
        # including forward slashes (/), which would otherwise be left
        # unencoded. This ensures paths like "group/subgroup/project"
        # become "group%2Fsubgroup%2Fproject" as required by the API.
        encoded_path: str = quote(self.project_path, safe="")
        self.api_url = (
            f"{self.server_url}/api/v4/projects/{encoded_path}/repository/tags"
        )

    @property
    def cache_key(self) -> str:
        return f"{self.server_url}/{self.project_path}"

    @retry_on_exception(
        exceptions=RETRYABLE_EXCEPTIONS,
        max_attempts=5,
        backoff_factor=1.5,
        max_backoff=120.0,
    )
    def _find_tags(
        self,
        identifier: str,
    ) -> Iterable[Candidate]:
        nexturl: str = self.api_url
        created_at: datetime.datetime | None
        while nexturl:
            resp: Response = session.get(nexturl)
            resp.raise_for_status()
            for entry in resp.json():
                tagname = entry["name"]
                version = self._match_function(identifier, tagname)
                if version is None:
                    logger.debug(f"{identifier}: match function ignores {tagname}")
                    continue
                assert isinstance(version, Version)

                archive_path: str = f"{self.project_path}/-/archive/{tagname}/{self.project_path.split('/')[-1]}-{tagname}.tar.gz"
                url = urljoin(self.server_url, archive_path)

                # get tag creation time, fall back to commit creation time
                created_at_str: str | None = entry.get("created_at")
                if created_at_str is None:
                    created_at_str = entry["commit"].get("created_at")

                if created_at_str is not None:
                    created_at = datetime.datetime.fromisoformat(
                        created_at_str
                    ).astimezone(datetime.UTC)
                else:
                    created_at = None

                yield Candidate(
                    name=identifier,
                    version=version,
                    url=url,
                    remote_tag=tagname,
                    remote_commit=entry["commit"]["id"],
                    upload_time=created_at,
                )

            # GitLab API uses Link headers for pagination
            nexturl = resp.links.get("next", {}).get("url")
