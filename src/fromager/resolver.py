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
from urllib.parse import quote, unquote, urlparse

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
from .candidate import Candidate, Cooldown
from .constraints import Constraints
from .extras_provider import ExtrasProvider
from .http_retry import RETRYABLE_EXCEPTIONS, retry_on_exception
from .request_session import session
from .requirements_file import RequirementType
from .versionmap import VersionMap

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
    """Resolve requirement and return the best matching version.

    Returns (url, version) tuple for the highest matching version.
    """
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
    provider.cooldown = resolve_package_cooldown(ctx, req, req_type=req_type)
    max_age_cutoff = _compute_max_age_cutoff(ctx)
    results = find_all_matching_from_provider(
        provider, req, max_age_cutoff=max_age_cutoff
    )
    return results[0]


def default_resolver_provider(
    ctx: context.WorkContext,
    req: Requirement,
    sdist_server_url: str,
    include_sdists: bool,
    include_wheels: bool,
    req_type: RequirementType | None = None,
    ignore_platform: bool = False,
) -> (
    PyPIProvider
    | GenericProvider
    | GitHubTagProvider
    | GitLabTagProvider
    | VersionMapProvider
):
    """Lookup resolver provider to resolve package versions"""
    return PyPIProvider(
        include_sdists=include_sdists,
        include_wheels=include_wheels,
        sdist_server_url=sdist_server_url,
        constraints=ctx.constraints,
        req_type=req_type,
        ignore_platform=ignore_platform,
    )


def _has_equality_pin(req: Requirement) -> bool:
    """Return True if the requirement has a single exact ``==`` pin.

    Rejects wildcard pins (``==1.*``) and compound specifiers (``==1,>2``)
    which are not true exact version pins.
    """
    specs = list(req.specifier)
    return len(specs) == 1 and specs[0].operator == "==" and "*" not in specs[0].version


def resolve_package_cooldown(
    ctx: context.WorkContext,
    req: Requirement,
    req_type: RequirementType | None = None,
) -> Cooldown | None:
    """Compute the effective cooldown for a single package.

    Args:
        ctx: The current work context (provides the global cooldown).
        req: The package requirement being resolved.
        req_type: The requirement type (top-level, install, etc.).

    Returns:
        The cooldown to pass to the provider, or ``None`` if disabled.
    """
    if req_type == RequirementType.TOP_LEVEL and _has_equality_pin(req):
        if ctx.cooldown is not None:
            logger.info("cooldown bypassed as the top-level requirement uses == pin")
        return None

    per_package_days = ctx.package_build_info(req).resolver_min_release_age
    global_cooldown = ctx.cooldown
    if per_package_days is None:
        return global_cooldown
    if per_package_days == 0:
        return None
    # Per-package positive override: inherit bootstrap_time from global so all
    # resolutions in a single run share the same fixed cutoff point.
    bootstrap_time = (
        global_cooldown.bootstrap_time
        if global_cooldown is not None
        else datetime.datetime.now(datetime.UTC)
    )
    return Cooldown(
        min_age=datetime.timedelta(days=per_package_days),
        bootstrap_time=bootstrap_time,
    )


def _compute_max_age_cutoff(
    ctx: context.WorkContext,
) -> datetime.datetime | None:
    """Compute the cutoff time for max release age filtering.

    Returns the oldest acceptable upload time, or None if disabled.
    Uses the cooldown's bootstrap_time for consistency across a single run.
    """
    if ctx.max_release_age is None:
        return None
    bootstrap_time = (
        ctx.cooldown.bootstrap_time
        if ctx.cooldown is not None
        else datetime.datetime.now(datetime.UTC)
    )
    return bootstrap_time - ctx.max_release_age


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

    def rejecting_candidate(self, criterion: typing.Any, candidate: typing.Any) -> None:
        self._report("resolver rejecting candidate %s: %s", candidate, criterion)

    def pinning(self, candidate: typing.Any) -> None:
        self._report("selecting %s", candidate)

    def ending(self, state: typing.Any) -> None:
        self._report("successfully resolved %r", self.req)


def find_all_matching_from_provider(
    provider: BaseProvider,
    req: Requirement,
    max_age_cutoff: datetime.datetime | None = None,
) -> list[tuple[str, Version]]:
    """Find all matching candidates from provider without full dependency resolution.

    This function collects ALL candidates that match the requirement, rather than
    performing full dependency resolution to find a single best candidate.

    Args:
        provider: The provider to query for candidates.
        req: The requirement to match.
        max_age_cutoff: If set, reject candidates published before this time.
            If all candidates are older than the cutoff, all are kept and
            a warning is emitted to avoid empty resolution.

    Returns list of (url, version) tuples sorted by version (highest first).

    IMPORTANT: This bypasses resolvelib's full resolver to collect all matching
    candidates. This is safe ONLY because BaseProvider.get_dependencies() returns
    an empty list (no transitive dependencies to resolve). The empty incompatibilities
    dict means no version is ever excluded based on conflicts.

    If get_dependencies() is ever extended to return actual dependencies, this
    function must be revisited to use resolvelib's full resolution algorithm
    (Resolver.resolve()) to properly handle dependency conflicts and backtracking.
    """
    # Get all matching candidates directly from provider
    # instead of using resolvelib's resolver which picks just one
    identifier = provider.identify(req)
    try:
        # Bypass resolvelib's resolver to collect all matching candidates rather than
        # just the single best one. This is safe because get_dependencies() returns []
        # (no transitive deps to resolve). If get_dependencies() is ever extended,
        # this must be revisited to use resolvelib's full resolution.
        candidates = provider.find_matches(
            identifier=identifier,
            requirements={identifier: [req]},
            incompatibilities={},  # Empty - safe only because no transitive deps
        )
    except resolvelib.resolvers.ResolverException as err:
        constraint = provider.constraints.get_constraint(req.name)
        provider_desc = provider.get_provider_description()
        original_msg = str(err)
        raise resolvelib.resolvers.ResolverException(
            f"Unable to resolve requirement specifier {req} with constraint {constraint} using {provider_desc}: {original_msg}"
        ) from err

    # Materialize candidates so we can iterate more than once if filtering
    candidates_list = list(candidates)

    if max_age_cutoff is not None:
        logger.info(
            "%s: found %d candidate(s) matching %s",
            req.name,
            len(candidates_list),
            req,
        )
        max_age_days = (datetime.datetime.now(datetime.UTC) - max_age_cutoff).days
        filtered = [
            c
            for c in candidates_list
            if c.upload_time is None or c.upload_time >= max_age_cutoff
        ]
        dropped = len(candidates_list) - len(filtered)
        if dropped:
            logger.info(
                "%s: have %d candidate(s) of %s published within %d days",
                req.name,
                len(filtered),
                req,
                max_age_days,
            )
        if filtered:
            candidates_list = filtered
        else:
            logger.warning(
                "%s: all %d candidate(s) of %s are older than %d days, "
                "keeping all to avoid empty resolution",
                req.name,
                len(candidates_list),
                req,
                max_age_days,
            )

    # Convert candidates to list of (url, version) tuples
    # Candidates are sorted by version (highest first) by BaseProvider.find_matches()
    # which calls sorted(candidates, key=attrgetter("version", "build_tag"), reverse=True)
    return [(c.url, c.version) for c in candidates_list]


def get_project_from_pypi(
    project: str,
    extras: typing.Iterable[str],
    sdist_server_url: str,
    ignore_platform: bool = False,
    *,
    override_download_url: str | None = None,
) -> Candidates:
    """Fetch and filter package candidates from a PyPI-compatible server.

    Filters the project's package list by: project status, filename
    validity, package type (sdist/wheel), yanked status, Python version
    compatibility, and platform tags. Can substitute
    ``override_download_url`` into each candidate's URL.
    """
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

        if override_download_url is None:
            url = dp.url
        else:
            url = override_download_url.format(version=version)

        upload_time = dp.upload_time
        if upload_time is not None:
            upload_time = upload_time.astimezone(datetime.UTC)

        c = Candidate(
            name=name,
            version=version,
            url=url,
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


type RequirementsMap = typing.Mapping[str, typing.Iterable[Requirement]]
type Candidates = typing.Iterable[Candidate]
type CandidatesMap = typing.Mapping[str, Candidates]
# {identifier: [cls, cachekey]: list[candidates]}}
type ResolverCache = dict[str, dict[tuple[type[ExtrasProvider], str], list[Candidate]]]
type VersionSource = typing.Callable[
    [str],
    typing.Iterable[Candidate | tuple[str, str | Version]],
]


class BaseProvider(ExtrasProvider):
    resolver_cache: typing.ClassVar[ResolverCache] = {}
    provider_description: typing.ClassVar[str]
    _cooldown_unsupported_warned: typing.ClassVar[set[str]] = set()

    def __init__(
        self,
        *,
        constraints: Constraints | None = None,
        req_type: RequirementType | None = None,
        use_resolver_cache: bool = True,
        cooldown: Cooldown | None = None,
    ):
        super().__init__()
        self.constraints = constraints or Constraints()
        self.req_type = req_type
        self.use_cache_candidates = use_resolver_cache

        # cooldown specific settings
        self.cooldown = cooldown
        # Does this provider supply upload timestamps for candidates?
        # Defaults to False (safe/unknown). Subclasses that reliably populate
        # upload_time on every candidate should set this to True in their __init__.
        # When a cooldown is active and this is False, the cooldown check is
        # skipped with a warning rather than failing closed.
        self.supports_upload_time: bool = False

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
        identifier_reqs = list(requirements.get(identifier, []))
        bad_versions = {c.version for c in incompatibilities.get(identifier, [])}
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

    def is_blocked_by_cooldown(self, candidate: Candidate) -> bool:
        """Return True if the candidate is rejected by the release-age cooldown."""

        # a cooldown is not specified...
        if self.cooldown is None:
            return False

        # the target candidate doesn't provide a valid upload timestamp
        if candidate.upload_time is None:
            if not self.supports_upload_time:
                # this provider does not yet support timestamp retrieval (e.g. GitHub).
                # Warn once per package name across all provider instances.
                if candidate.name not in BaseProvider._cooldown_unsupported_warned:
                    BaseProvider._cooldown_unsupported_warned.add(candidate.name)
                    logger.warning(
                        "release-age cooldown cannot be enforced — upload "
                        "timestamp support is not yet implemented for %s; "
                        "cooldown check skipped",
                        self.get_provider_description(),
                    )
                return False
            # this provider is expected to supply timestamps,
            # but this candidate is missing one.
            # Fail closed: we cannot verify the age of this candidate, so reject it.
            if DEBUG_RESOLVER:
                logger.debug(
                    "skipping %s — upload_time unknown, required for cooldown",
                    candidate.version,
                )
            return True

        # cooldowns are enabled, and this candidate has a valid upload timestamp
        # so we can do the math to determine whether or not the candidate should
        # be blocked/skipped
        cutoff = self.cooldown.bootstrap_time - self.cooldown.min_age
        if candidate.upload_time > cutoff:
            # if this candidate is "too new", block/skip it
            if DEBUG_RESOLVER:
                age = self.cooldown.bootstrap_time - candidate.upload_time
                logger.debug(
                    "skipping %s uploaded %s ago (cooldown: %s)",
                    candidate.version,
                    age,
                    self.cooldown.min_age,
                )
            return True
        return False

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
        reqs = requirements.get(identifier, [])
        if reqs:
            r = next(iter(reqs))
            return f"found no match for {r} using {self.get_provider_description()}"
        return f"found no match for identifier {identifier} using {self.get_provider_description()}"

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
        # Apply cooldown filtering after specifier/constraint validation
        blocked = [c for c in candidates if self.is_blocked_by_cooldown(c)]
        if blocked:
            for b in blocked:
                candidates.remove(b)
            versions = ", ".join(str(b.version) for b in blocked)
            logger.info(
                "cooldown blocked %d version(s): %s",
                len(blocked),
                versions,
            )
        if not candidates:
            raise resolvelib.resolvers.ResolverException(
                self._get_no_match_error_message(identifier, requirements)
            )
        return sorted(candidates, key=attrgetter("version", "build_tag"), reverse=True)


class PyPIProvider(BaseProvider):
    """Lookup package and versions from a simple Python index (PyPI)

    The ``override_download_url`` parameter supports the string template variable:
    * version (Version object)
    """

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
        override_download_url: str | None = None,
        cooldown: Cooldown | None = None,
        supports_upload_time: bool | None = None,
    ):
        super().__init__(
            constraints=constraints,
            req_type=req_type,
            use_resolver_cache=use_resolver_cache,
            cooldown=cooldown,
        )

        # Only pypi.org reliably supports PEP 691 upload timestamps.
        # Default to True for pypi.org, False for all other indexes.
        if supports_upload_time is None:
            supports_upload_time = sdist_server_url.startswith(PYPI_SERVER_URL)
        self.supports_upload_time = supports_upload_time
        self.include_sdists = include_sdists
        self.include_wheels = include_wheels
        self.sdist_server_url = sdist_server_url
        self.ignore_platform = ignore_platform
        self.override_download_url = override_download_url

    @property
    def cache_key(self) -> str:
        # ignore platform parameter changes behavior of find_candidates()
        key = self.sdist_server_url
        if self.override_download_url is not None:
            key = f"{key}+{self.override_download_url}"
        if self.ignore_platform:
            key = f"{key}+ignore_platform"
        return key

    def find_candidates(self, identifier: str) -> Candidates:
        return get_project_from_pypi(
            identifier,
            extras=set(),
            sdist_server_url=self.sdist_server_url,
            ignore_platform=self.ignore_platform,
            override_download_url=self.override_download_url,
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

        # If a cooldown is active, check whether it's responsible for the
        # failure so we can give a more actionable error message.
        if self.cooldown is not None:
            cutoff = self.cooldown.bootstrap_time - self.cooldown.min_age
            all_candidates = list(self._find_cached_candidates(identifier))
            missing_time = [c for c in all_candidates if c.upload_time is None]
            cooldown_blocked = [
                c
                for c in all_candidates
                if c.upload_time is not None and c.upload_time > cutoff
            ]
            if missing_time and not cooldown_blocked:
                return (
                    f"found {len(missing_time)} candidate(s) for {r} but none have "
                    f"upload timestamp metadata; {self.sdist_server_url!r} may not "
                    f"support PEP 691 (JSON API), which is required to enforce the "
                    f"{self.cooldown.min_age.days}-day release-age cooldown"
                )
            if cooldown_blocked:
                oldest_days = min(
                    (self.cooldown.bootstrap_time - c.upload_time).days
                    for c in cooldown_blocked
                    if c.upload_time is not None
                )
                return (
                    f"found {len(cooldown_blocked)} candidate(s) for {r} but all "
                    f"were published within the last {self.cooldown.min_age.days} days "
                    f"(release-age cooldown; oldest is {oldest_days} day(s) old)"
                )

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
        cooldown: Cooldown | None = None,
    ):
        super().__init__(
            constraints=constraints,
            req_type=req_type,
            use_resolver_cache=use_resolver_cache,
            cooldown=cooldown,
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

    def find_candidates(self, identifier: typing.Any) -> Candidates:
        """Find matching candidates from the version source.

        Accepts three input formats from _version_source:
        1. Candidate objects (used directly)
        2. (url, Version) tuples
        3. (url, str) tuples (version parsed via _match_function)
        """
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

    The ``override_download_url`` parameter supports the string template variable:
    * organization
    * repo
    * tagname
    * version (Version object)
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
        override_download_url: str | None = None,
        cooldown: Cooldown | None = None,
    ):
        super().__init__(
            constraints=constraints,
            req_type=req_type,
            use_resolver_cache=use_resolver_cache,
            version_source=self._find_tags,
            matcher=matcher,
            cooldown=cooldown,
        )
        self.organization = organization
        self.repo = repo
        self.override_download_url = override_download_url

    @property
    def cache_key(self) -> str:
        key = f"{self.organization}/{self.repo}"
        if self.override_download_url is not None:
            key = f"{key}+{self.override_download_url}"
        return key

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

                if self.override_download_url is None:
                    url = entry["tarball_url"]
                else:
                    url = self.override_download_url.format(
                        organization=self.organization,
                        repo=self.repo,
                        tagname=tagname,
                        version=version,
                    )

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
    """Lookup tarball and version from GitLab git tags

    The ``override_download_url`` parameter supports the string template variable:
    * hostname
    * project_path
    * project_name (last component of project_path)
    * tagname
    * version (Version object)
    """

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
        override_download_url: str | None = None,
        cooldown: Cooldown | None = None,
    ) -> None:
        super().__init__(
            constraints=constraints,
            req_type=req_type,
            use_resolver_cache=use_resolver_cache,
            version_source=self._find_tags,
            matcher=matcher,
            cooldown=cooldown,
        )
        self.supports_upload_time = True
        self.server_url = server_url.rstrip("/")
        self.server_hostname = urlparse(server_url).hostname
        if not self.server_hostname:
            raise ValueError(f"invalid {server_url=}")
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
        self.override_download_url = override_download_url

    @property
    def cache_key(self) -> str:
        key = f"{self.server_url}/{self.project_path}"
        if self.override_download_url is not None:
            key = f"{key}+{self.override_download_url}"
        return key

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
        project_name = self.project_path.split("/")[-1]
        if self.override_download_url is None:
            download_template = (
                self.server_url
                + "/{project_path}/-/archive/{tagname}/{project_name}-{tagname}.tar.gz"
            )
        else:
            download_template = self.override_download_url
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

                url = download_template.format(
                    hostname=self.server_hostname,
                    project_path=self.project_path,
                    project_name=project_name,
                    tagname=tagname,
                    version=version,
                )

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


class VersionMapProvider(BaseProvider):
    """Lookup package versions from a VersionMap

    This provider wraps a VersionMap instance to provide versions and URLs
    for package resolution. The VersionMap should contain Version keys mapped
    to URL strings.
    """

    provider_description: typing.ClassVar[str] = (
        "VersionMap resolver (package: {self.package_name})"
    )

    def __init__(
        self,
        version_map: VersionMap,
        package_name: str,
        constraints: Constraints | None = None,
        *,
        req_type: RequirementType | None = None,
        use_resolver_cache: bool = True,
    ) -> None:
        super().__init__(
            constraints=constraints,
            req_type=req_type,
            use_resolver_cache=use_resolver_cache,
        )
        self.version_map = version_map
        self.package_name = package_name

    @property
    def cache_key(self) -> str:
        return f"versionmap:{self.package_name}"

    def find_candidates(self, identifier: str) -> Candidates:
        """Find candidates from the VersionMap

        Iterates through all versions in the VersionMap and creates Candidate
        objects with the associated URLs.
        """
        candidates: list[Candidate] = []
        for version in self.version_map.versions():
            url = self.version_map[version]
            candidate = Candidate(
                name=identifier,
                version=version,
                url=url,
            )
            candidates.append(candidate)

        return candidates
