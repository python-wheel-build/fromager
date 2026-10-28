from __future__ import annotations

import dataclasses
import enum
import inspect
import logging
import pathlib
import re
import shutil
import typing

import pydantic
from packaging.utils import canonicalize_name

from .. import downloads, overrides, resolver
from ._typedefs import MODEL_CONFIG

if typing.TYPE_CHECKING:
    from packaging.requirements import Requirement
    from packaging.version import Version

    from .. import context, requirements_file

logger = logging.getLogger(__name__)

_VERSION_QUOTED = "%7Bversion%7D"
_PYPI_INDEX_URL = pydantic.HttpUrl("https://pypi.org/simple/")


class BuildSDist(enum.StrEnum):
    pep517 = "pep517"
    tarball = "tarball"


class DownloadKind(enum.StrEnum):
    """Kind of artifact that the resolver downloads."""

    sdist = "sdist"
    tarball = "tarball"
    prebuilt_wheel = "prebuilt_wheel"
    git_checkout = "git_checkout"
    any_source = "any_source"
    not_available = "n/a"

    def __bool__(self) -> bool:
        return self is not DownloadKind.not_available


DownloadKindSet = frozenset[DownloadKind]


@dataclasses.dataclass(frozen=True, slots=True)
class DownloadedSource:
    """Immutable result of downloading an artifact.

    ``path`` is the local artifact path. ``kind`` identifies how the artifact
    should be handled; hook resolvers require a concrete, supported kind.

    .. versionadded:: 0.96.0
    """

    path: pathlib.Path
    kind: DownloadKind


class AbstractResolver(pydantic.BaseModel):
    """Abstract base class for resolvers"""

    model_config = MODEL_CONFIG

    provider: str

    build_sdist: BuildSDist | None
    """Sdist build strategy; None for resolvers that do not build from source."""

    supports_override_hooks: typing.ClassVar[bool] = False
    """Does resolver support override hooks?"""

    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset()
    """Set of download kinds this resolver can return."""

    resolves_prebuilt_wheel: typing.ClassVar[bool] = False
    """Does resolver return pre-built wheels?"""

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
    ) -> resolver.BaseProvider:
        """Return a resolver provider for the given requirement."""
        raise NotImplementedError

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
    ) -> DownloadedSource:
        """Download the resolved artifact for *version* from *download_url*.

        Resolution and download can run in different commands, for example
        ``bootstrap`` and then ``build-sequence``. Only the version and URL
        are saved between them, so they are all a download receives.
        *download_url* must contain everything the download needs, such as
        the git ref in ``git+https://host/repo.git@refs/tags/v1.0``. It is
        passed to download hooks unchanged and is not validated, so it can be
        a ref instead of a URL, such as a commit SHA from a
        ``VersionMapProvider``.
        """
        raise NotImplementedError

    def _download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
        download_kind: DownloadKind,
    ) -> DownloadedSource:
        """Download the resolved artifact for *version* from *download_url*.

        Returns the local path and the kind of artifact that was
        downloaded.  Dispatches to the appropriate download helper
        based on *download_kind*.
        """
        if download_kind not in self.download_kinds:
            raise ValueError(
                f"provider {self.provider!r} does not support download kind "
                f"{download_kind!r}, expected one of {self.download_kinds!r}"
            )
        match download_kind:
            case DownloadKind.sdist:
                destination_dir = ctx.sdists_downloads
                path = downloads.download_sdist(
                    destination_dir=destination_dir,
                    url=download_url,
                )
            case DownloadKind.tarball:
                # TODO: A tarball is not a proper sdist; it should not
                # live in sdists_downloads.  Using it here for now until
                # a dedicated tarballs directory is introduced.
                destination_dir = ctx.sdists_downloads
                # GitHub tarball URLs have no usable filename in the
                # path, so always provide a destination filename.
                path = downloads.download_url(
                    destination_dir=destination_dir,
                    url=download_url,
                    destination_filename=(
                        f"{canonicalize_name(req.name)}-{version}.tar.gz"
                    ),
                )
            case DownloadKind.prebuilt_wheel:
                destination_dir = ctx.wheels_prebuilt
                path = downloads.download_wheel(
                    destination_dir=destination_dir,
                    url=download_url,
                )
            case DownloadKind.git_checkout:
                # TODO: Maybe use dedicated directory like
                # 'work_dir / f"{name}-{version}" / "checkout"' for
                # checkout, generate a proper sdist, then unpack to
                # final destination?
                destination_dir = (
                    ctx.work_dir / f"{req.name}-{version}" / f"{req.name}-{version}"
                )
                if destination_dir.parent.exists():
                    if ctx.cleanup:
                        shutil.rmtree(destination_dir.parent)
                    elif destination_dir.exists():
                        raise FileExistsError(
                            f"Git checkout {destination_dir} already exists; "
                            "enable cleanup or use a new work directory to download it again"
                        )
                path = downloads.download_git_source(
                    destination_dir=destination_dir,
                    vcs_url=download_url,
                )
            case _:  # includes any_source and not_available
                typing.assert_never(download_kind)  # type: ignore[arg-type]
        return DownloadedSource(path=path, kind=download_kind)


class CooldownMixin(pydantic.BaseModel):
    min_release_age: int | None = pydantic.Field(default=None, ge=0)
    """Minimum release age override in days.

    None (default): inherit the global ``--min-release-age`` setting.
    0: disable the release-age cooldown for this package.
    Positive integer: override the cooldown with this many days.
    """


class AbstractPyPIResolver(AbstractResolver, CooldownMixin):
    """Abstract base class for PyPI resolvers"""

    index_url: pydantic.HttpUrl = pydantic.Field(
        default=_PYPI_INDEX_URL,
        description="Python Package Index URL",
    )


class PyPISDistResolver(AbstractPyPIResolver):
    """Resolve version with PyPI, download sdist from PyPI

    The ``pypi-sdist`` provider uses :pep:`503` *Simple Repository API* or
    :pep:`691` *JSON-based Simple API* to resolve packages on PyPI or a
    PyPI-compatible index.

    The provider downloads source distributions (tarballs) from the index.
    It ignores releases that have only wheels and no sdist.

    Example::

        provider: pypi-sdist
        index_url: https://pypi.test/simple
    """

    provider: typing.Literal["pypi-sdist"]

    # It is not safe to use PEP 517 to re-generate a source distribution.
    # Some PEP 517 backends require VCS to generate correct sdist.
    build_sdist: typing.Literal[BuildSDist.tarball] = BuildSDist.tarball
    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset({DownloadKind.sdist})

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
    ) -> resolver.PyPIProvider:
        return resolver.PyPIProvider(
            include_sdists=True,
            include_wheels=False,
            sdist_server_url=str(self.index_url),
            constraints=ctx.constraints,
            req_type=req_type,
            ignore_platform=False,
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
    ) -> DownloadedSource:
        """Download an sdist from PyPI."""
        return self._download(ctx, req, version, download_url, DownloadKind.sdist)


class PyPIPrebuiltResolver(AbstractPyPIResolver):
    """Resolve version with PyPI, download pre-built wheel from PyPI

    The ``pypi-prebuilt`` provider uses :pep:`503` *Simple Repository API* or
    :pep:`691` *JSON-based Simple API* to resolve packages on PyPI or a
    PyPI-compatible index.

    The provider downloads pre-built wheels from the index. It ignores
    versions that have no compatible wheels (sdist-only or incompatible
    OS, CPU arch, or glibc version).

    Example::

        provider: pypi-prebuilt
        index_url: https://pypi.test/simple
    """

    provider: typing.Literal["pypi-prebuilt"]

    build_sdist: None = None
    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset(
        {DownloadKind.prebuilt_wheel}
    )
    resolves_prebuilt_wheel: typing.ClassVar[bool] = True

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
    ) -> resolver.PyPIProvider:
        return resolver.PyPIProvider(
            include_sdists=False,
            include_wheels=True,
            sdist_server_url=str(self.index_url),
            constraints=ctx.constraints,
            req_type=req_type,
            ignore_platform=False,
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
    ) -> DownloadedSource:
        """Download a pre-built wheel from PyPI."""
        return self._download(
            ctx, req, version, download_url, DownloadKind.prebuilt_wheel
        )


class PyPIDownloadResolver(AbstractPyPIResolver):
    """Resolve version with PyPI, download sdist from arbitrary URL

    The ``pypi-download`` provider uses :pep:`503` *Simple Repository API* or
    :pep:`691` *JSON-based Simple API* to resolve packages on PyPI or a
    PyPI-compatible index.

    The provider takes all releases into account (sdist-only, wheel-only,
    even incompatible wheels).

    It downloads tarball from an alternative download location. The download
    URL must contain a ``{version}`` template, e.g.
    ``https://download.example/mypackage-{version}.tar.gz``.

    Example::

        provider: pypi-download
        index_url: https://pypi.test/simple
        download_url: https://download.test/test_pypidownload-{version}.tar.gz
        download_kind: tarball
    """

    provider: typing.Literal["pypi-download"]

    download_url: pydantic.HttpUrl
    """Remote download URL

    URL must contain '{version}' template string.
    """

    build_sdist: typing.Literal[BuildSDist.tarball] = BuildSDist.tarball
    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset(
        {DownloadKind.sdist, DownloadKind.tarball}
    )

    download_kind: typing.Literal[DownloadKind.sdist, DownloadKind.tarball]
    """Kind of artifact that the resolver downloads."""

    @pydantic.field_validator("download_url", mode="after")
    @classmethod
    def validate_download_url(cls, value: pydantic.HttpUrl) -> pydantic.HttpUrl:
        if not value.path:
            raise ValueError(f"url {value} has an empty path")
        if _VERSION_QUOTED not in value.path:
            raise ValueError(f"missing '{{version}}' in url {value}")
        return value

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
    ) -> resolver.PyPIProvider:
        return resolver.PyPIProvider(
            include_sdists=True,
            include_wheels=True,
            sdist_server_url=str(self.index_url),
            constraints=ctx.constraints,
            req_type=req_type,
            ignore_platform=True,
            override_download_url=str(self.download_url).replace(
                _VERSION_QUOTED, "{version}"
            ),
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
    ) -> DownloadedSource:
        """Download an sdist or tarball from a custom URL."""
        return self._download(ctx, req, version, download_url, self.download_kind)


class PyPIGitResolver(AbstractPyPIResolver):
    """Resolve version with PyPI, build sdist from git clone

    The ``pypi-git`` provider uses :pep:`503` *Simple Repository API* or
    :pep:`691` *JSON-based Simple API* to resolve packages on PyPI or a
    PyPI-compatible index.

    The provider takes all releases into account (sdist-only, wheel-only,
    even incompatible wheels).

    It clones and retrieves a git repo + recursive submodules at a specific
    tag. The tag must contain ``{version}`` template.

    Example::

       provider: pypi-git
       index_url: https://pypi.test/simple
       clone_url: https://code.test/project/repo.git
       tag: 'v{version}'
       build_sdist: pep517
    """

    provider: typing.Literal["pypi-git"]

    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset(
        {DownloadKind.git_checkout}
    )

    clone_url: pydantic.AnyUrl
    """git clone URL

    https://git.test/repo.git
    """

    tag: str = pydantic.Field(pattern=r".*version.*")
    """Tag template containing a ``version`` reference.

    Supports simple substitution (``{version}``) and f-string
    expressions like ``{version.major}_{version.minor}``.
    """

    build_sdist: BuildSDist = BuildSDist.pep517
    """Source distribution build method"""

    @pydantic.field_validator("clone_url", mode="after")
    @classmethod
    def validate_clone_url(cls, value: pydantic.AnyUrl) -> pydantic.AnyUrl:
        if value.scheme not in {"https", "ssh"}:
            raise ValueError(f"invalid scheme in url {value}")
        if not value.path:
            raise ValueError(f"url {value} has an empty path")
        return value

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
    ) -> resolver.PyPIProvider:
        download_url = f"git+{self.clone_url}@refs/tags/{self.tag}"
        return resolver.PyPIProvider(
            include_sdists=True,
            include_wheels=True,
            sdist_server_url=str(self.index_url),
            constraints=ctx.constraints,
            req_type=req_type,
            ignore_platform=True,
            override_download_url=download_url,
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
    ) -> DownloadedSource:
        """Clone a git repository at a specific tag."""
        return self._download(
            ctx, req, version, download_url, DownloadKind.git_checkout
        )


_PEP440_TAG_PATTERN = re.compile(r"^(v?\d.*)$")


def pep440_tag_matcher(ctx: context.WorkContext) -> re.Pattern:
    """Matcher factory for PEP 440-like version tags.

    Matches tags starting with an optional ``v`` prefix followed by a digit,
    e.g. ``v1.0``, ``1.2.3``, ``v2.0rc1``. This is a heuristic to detect
    likely version tags, not a full :pep:`440` compliance check.
    """
    return _PEP440_TAG_PATTERN


class AbstractGitSourceResolver(AbstractResolver, CooldownMixin):
    """Common abstract class for GitHub and GitLab resolver"""

    project_url: pydantic.HttpUrl
    """Full project URL"""

    matcher_factory: pydantic.ImportString = pep440_tag_matcher
    """Matcher factory import string (``package.module:name``)

    A factory function that accepts a *ctx* arg and returns a
    :class:`re.Pattern` or :class:`~fromager.resolver.MatchFunction`.
    """

    build_sdist: BuildSDist = BuildSDist.pep517
    """Source distribution build method"""

    @pydantic.field_validator("project_url", mode="after")
    @classmethod
    def validate_url(cls, value: pydantic.HttpUrl) -> pydantic.HttpUrl:
        """Validate that URL is https URL with host and path"""
        if value.scheme != "https" or not value.host or not value.path:
            raise ValueError(f"invalid url {value}: expected https, hostname, and path")
        if value.path.endswith(".git"):
            raise ValueError(f"invalid url {value}: path ends with '.git'")
        return value

    @pydantic.field_validator("matcher_factory", mode="after")
    @classmethod
    def validate_matcher(cls, value: typing.Callable) -> typing.Callable:
        """Validate that matcher factory is a callable with ``func(ctx)`` signature."""
        if not callable(value):
            raise TypeError(f"{value} is not callable")
        sig = inspect.signature(value)
        if list(sig.parameters) != ["ctx"]:
            raise TypeError(
                f"{value} has an invalid signature {sig}, expected 'func(ctx)'."
            )
        return value

    def _get_matcher(
        self, ctx: context.WorkContext
    ) -> re.Pattern | resolver.MatchFunction:
        """Call the matcher factory and validate the returned matcher."""
        matcher = self.matcher_factory(ctx=ctx)  # type: ignore[call-arg]
        if isinstance(matcher, re.Pattern):
            if matcher.groups != 1:
                raise ValueError(
                    f"Expected a re pattern with exactly one match group, "
                    f"got {matcher.groups} groups for {matcher.pattern!r}."
                )
            return matcher
        elif callable(matcher):
            sig = inspect.signature(matcher)
            if list(sig.parameters) != ["identifier", "item"]:
                raise TypeError(
                    f"{matcher} has an invalid signature {sig}, "
                    f"expected 'func(identifier, item)'."
                )
            return typing.cast(resolver.MatchFunction, matcher)
        else:
            raise TypeError(
                f"matcher factory returned {type(matcher).__name__}, "
                f"expected re.Pattern or callable."
            )

    def _github_provider(
        self,
        *,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType | None,
        override_download_url: str | None = None,
    ) -> resolver.GitHubTagProvider:
        if self.project_url.host != "github.com":
            raise ValueError(f"Expected 'github.com' in {self.project_url}")
        if not self.project_url.path or self.project_url.path.count("/") != 2:
            raise ValueError(
                f"Invalid path in {self.project_url}, expected two elements"
            )
        organization, repo = self.project_url.path.lstrip("/").split("/")
        return resolver.GitHubTagProvider(
            organization=organization,
            repo=repo,
            constraints=ctx.constraints,
            matcher=self._get_matcher(ctx),
            req_type=req_type,
            override_download_url=override_download_url,
        )

    def _gitlab_provider(
        self,
        *,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType | None,
        override_download_url: str | None = None,
    ) -> resolver.GitLabTagProvider:
        if not self.project_url.path:
            raise ValueError(f"Empty path in {self.project_url}")
        return resolver.GitLabTagProvider(
            project_path=self.project_url.path.lstrip("/"),
            server_url=f"https://{self.project_url.host}:{self.project_url.port}",
            constraints=ctx.constraints,
            matcher=self._get_matcher(ctx),
            req_type=req_type,
            override_download_url=override_download_url,
        )


class GitHubTagDownloadResolver(AbstractGitSourceResolver):
    """Resolve  from GitHub tags, build sdist from a git tarball download

    The ``github`` provider uses GitHub's REST API to resolve versions from tags.

    Example::

       provider: github-tag-download
       project_url: https://github.com/python-wheel-build/fromager
       matcher_factory: fromager.packagesettings:pep440_tag_matcher
       build_sdist: pep517
    """

    provider: typing.Literal["github-tag-download"]

    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset({DownloadKind.tarball})

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
    ) -> resolver.GitHubTagProvider:
        return self._github_provider(
            ctx=ctx,
            req_type=req_type,
            override_download_url=None,
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
    ) -> DownloadedSource:
        """Download a tarball from a GitHub tag."""
        return self._download(ctx, req, version, download_url, DownloadKind.tarball)


class GitHubTagCloneResolver(AbstractGitSourceResolver):
    """Resolve version from GitHub tags, build sdist from a git clone

    The ``github`` provider uses GitHub's REST API to resolve versions from tags.

    Example::

       provider: github-tag-git
       project_url: https://github.com/python-wheel-build/fromager
       matcher_factory: fromager.packagesettings:pep440_tag_matcher
       build_sdist: pep517
    """

    provider: typing.Literal["github-tag-git"]

    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset(
        {DownloadKind.git_checkout}
    )

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
    ) -> resolver.GitHubTagProvider:
        return self._github_provider(
            ctx=ctx,
            req_type=req_type,
            override_download_url=f"git+{self.project_url}@{{tagname}}",
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
    ) -> DownloadedSource:
        """Clone a git repository from a GitHub tag."""
        return self._download(
            ctx, req, version, download_url, DownloadKind.git_checkout
        )


class GitLabTagDownloadResolver(AbstractGitSourceResolver):
    """Resolve version from GitLab tags, build sdist from a git tarball download

    The ``gitlab`` provider uses GitLab's REST API to resolve versions from tags.

    Example::

       provider: gitlab-tag-download
       project_url: https://gitlab.test/python-wheel-build/fromager
       matcher_factory: fromager.packagesettings:pep440_tag_matcher
       build_sdist: pep517
    """

    provider: typing.Literal["gitlab-tag-download"]

    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset({DownloadKind.tarball})

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
    ) -> resolver.GitLabTagProvider:
        return self._gitlab_provider(
            ctx=ctx,
            req_type=req_type,
            override_download_url=None,
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
    ) -> DownloadedSource:
        """Download a tarball from a GitLab tag."""
        return self._download(ctx, req, version, download_url, DownloadKind.tarball)


class GitLabTagCloneResolver(AbstractGitSourceResolver):
    """Resolve version from GitLab tags, build sdist from a git clone

    The ``gitlab`` provider uses GitLab's REST API to resolve versions from tags.

    Example::

       provider: gitlab-tag-git
       project_url: https://gitlab.test/python-wheel-build/fromager
       matcher_factory: fromager.packagesettings:pep440_tag_matcher
       build_sdist: pep517
    """

    provider: typing.Literal["gitlab-tag-git"]

    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset(
        {DownloadKind.git_checkout}
    )

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
    ) -> resolver.GitLabTagProvider:
        return self._gitlab_provider(
            ctx=ctx,
            req_type=req_type,
            override_download_url=f"git+{self.project_url}@{{tagname}}",
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
    ) -> DownloadedSource:
        """Clone a git repository from a GitLab tag."""
        return self._download(
            ctx, req, version, download_url, DownloadKind.git_checkout
        )


class NotAvailableResolver(AbstractResolver):
    """Prevent resolve and download"""

    provider: typing.Literal["not-available"]
    build_sdist: None = None

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
    ) -> resolver.BaseProvider:
        raise ValueError(f"package {req.name} is not available")

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
    ) -> DownloadedSource:
        """Raise because package is not available."""
        raise ValueError(f"package {req.name} is not available")


class AbstractHookResolver(AbstractResolver, CooldownMixin):
    """Abstract base class for hook-based resolvers"""

    supports_override_hooks: typing.ClassVar[bool] = True
    """Hook resolvers support override hooks."""

    hookless_provider: typing.ClassVar[str]
    """Profile to suggest for packages without hooks."""

    def _find_resolver_hook(self, req: Requirement) -> typing.Callable | None:
        """Return the package resolver hook, or None to resolve on the index.

        Resolving on the index needs a ``download_source`` hook to get the
        source. Raise when the package has neither hook.
        """
        hook = overrides.find_override_method(req.name, "get_resolver_provider")
        if hook is None and not overrides.find_override_method(
            req.name, "download_source"
        ):
            raise ValueError(
                f"{req.name}: source resolver {self.provider!r} requires a "
                "get_resolver_provider or download_source override hook; "
                f"use {self.hookless_provider!r} for a package without hooks"
            )
        return hook

    def _resolver_provider_from_hook(
        self,
        *,
        hook: typing.Callable,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
        sdist_server_url: str,
        include_sdists: bool,
        include_wheels: bool,
        ignore_platform: bool,
    ) -> resolver.BaseProvider:
        """Invoke the package resolver hook and validate its result."""
        try:
            provider = overrides.invoke(
                hook,
                ctx=ctx,
                req=req,
                include_sdists=include_sdists,
                include_wheels=include_wheels,
                sdist_server_url=sdist_server_url,
                req_type=req_type,
                ignore_platform=ignore_platform,
            )
        except Exception as err:
            raise RuntimeError(
                f"{req.name}: {self.provider!r} get_resolver_provider hook failed"
            ) from err

        if not isinstance(provider, resolver.BaseProvider):
            raise TypeError(
                f"{req.name}: {self.provider!r} get_resolver_provider hook "
                f"returned {type(provider).__name__}, expected "
                "fromager.resolver.BaseProvider"
            )
        return provider

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
    ) -> resolver.BaseProvider:
        raise NotImplementedError

    def _download_from_hook(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
        legacy_kind: DownloadKind,
    ) -> DownloadedSource:
        """Download with the package hook and normalize its result."""
        hook = overrides.find_override_method(req.name, "download_source")
        if hook is None:
            return self._download(ctx, req, version, download_url, legacy_kind)

        error_context = f"{req.name}: {self.provider!r} download_source hook"
        try:
            result: object = overrides.invoke(
                hook,
                ctx=ctx,
                req=req,
                version=version,
                download_url=download_url,
                sdists_downloads_dir=ctx.sdists_downloads,
            )
        except Exception as err:
            raise RuntimeError(f"{error_context} failed") from err

        logger.info("%s returned %s", error_context, result)
        if isinstance(result, DownloadedSource):
            downloaded = result
        elif isinstance(result, pathlib.Path):
            suffixes = (
                (".whl",)
                if legacy_kind is DownloadKind.prebuilt_wheel
                else (".tar.gz", ".zip")
            )
            if result.is_dir() or not result.name.endswith(suffixes):
                raise ValueError(
                    f"{error_context} returned legacy Path {result}; expected a "
                    f"{' or '.join(suffixes)} file. Return DownloadedSource with "
                    "an explicit supported DownloadKind for other artifact forms"
                )
            downloaded = DownloadedSource(path=result, kind=legacy_kind)
        else:
            raise TypeError(
                f"{error_context} returned {type(result).__name__}, "
                "expected pathlib.Path or DownloadedSource"
            )

        if not isinstance(downloaded.path, pathlib.Path):
            raise TypeError(
                f"{error_context}: DownloadedSource.path must be pathlib.Path, "
                f"got {type(downloaded.path).__name__}"
            )
        if not isinstance(downloaded.kind, DownloadKind):
            raise TypeError(
                f"{error_context}: DownloadedSource.kind must be DownloadKind, "
                f"got {type(downloaded.kind).__name__}"
            )
        if downloaded.kind not in self.download_kinds:
            supported = ", ".join(sorted(kind.value for kind in self.download_kinds))
            raise ValueError(
                f"{error_context} returned unsupported kind {downloaded.kind.value!r}; "
                f"expected DownloadedSource with one of: {supported}"
            )
        return downloaded


class HookSDistResolver(AbstractHookResolver):
    """Call resolver_provider and download_source hook, build from source

    The ``hook-sdist`` provider delegates resolution and download to
    plugin hooks. Either hook is optional, but not both. Without a resolver
    hook, versions come from ``index_url``. The downloaded artifact can be a
    source distribution, a tarball, or a git checkout. Download hooks can
    return ``DownloadedSource`` with a concrete kind, or a legacy archive
    ``Path`` treated as an sdist.
    Without a download hook, the resolved URL is downloaded as an sdist.
    Specify ``build_sdist`` explicitly: ``tarball`` to repack an existing
    sdist, or ``pep517`` to build from a git checkout.

    Example::

        provider: hook-sdist
        index_url: https://pypi.test/simple
        build_sdist: tarball
    """

    provider: typing.Literal["hook-sdist"]
    build_sdist: BuildSDist
    """Source distribution build method."""

    index_url: pydantic.HttpUrl = pydantic.Field(
        default=_PYPI_INDEX_URL,
        description="Python Package Index URL",
    )

    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset(
        {DownloadKind.sdist, DownloadKind.tarball, DownloadKind.git_checkout}
    )
    hookless_provider: typing.ClassVar[str] = "pypi-sdist"

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
    ) -> resolver.BaseProvider:
        """Return a source provider from the resolver hook or the index.

        Without a ``get_resolver_provider`` hook, find versions on
        ``index_url`` in sdists and wheels for any platform, like
        ``pypi-git``. The ``download_source`` hook then gets the source.
        """
        hook = self._find_resolver_hook(req)
        if hook is None:
            return resolver.PyPIProvider(
                include_sdists=True,
                include_wheels=True,
                sdist_server_url=str(self.index_url),
                constraints=ctx.constraints,
                req_type=req_type,
                ignore_platform=True,
            )
        return self._resolver_provider_from_hook(
            hook=hook,
            ctx=ctx,
            req=req,
            req_type=req_type,
            sdist_server_url=str(self.index_url),
            include_sdists=True,
            include_wheels=False,
            ignore_platform=False,
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
    ) -> DownloadedSource:
        """Download source via the ``download_source`` override hook."""
        return self._download_from_hook(
            ctx, req, version, download_url, DownloadKind.sdist
        )


class HookPrebuiltResolver(AbstractHookResolver):
    """Call resolver_provider and download_source hook, use pre-built wheel

    The ``hook-prebuilt`` provider delegates resolution and download to
    plugin hooks. Either hook is optional, but not both. Without a resolver
    hook, versions come from ``index_url``. The downloaded artifact must be a
    pre-built wheel. Download hooks can return ``DownloadedSource`` with kind
    ``prebuilt_wheel`` or a legacy wheel ``Path``. Without a download hook,
    the resolved URL is downloaded into ``ctx.wheels_prebuilt``.

    Example::

        provider: hook-prebuilt
        index_url: https://wheels.test/simple
    """

    provider: typing.Literal["hook-prebuilt"]
    build_sdist: None = None

    index_url: pydantic.HttpUrl = pydantic.Field(
        description="Python Package Index URL for pre-built wheels",
    )

    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset(
        {DownloadKind.prebuilt_wheel}
    )
    resolves_prebuilt_wheel: typing.ClassVar[bool] = True
    hookless_provider: typing.ClassVar[str] = "pypi-prebuilt"

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType | None,
    ) -> resolver.BaseProvider:
        """Return a pre-built wheel provider from the resolver hook or the index.

        Without a ``get_resolver_provider`` hook, find versions on
        ``index_url`` in wheels for this platform, like ``pypi-prebuilt``.
        The ``download_source`` hook then gets the wheel.
        """
        hook = self._find_resolver_hook(req)
        if hook is None:
            return resolver.PyPIProvider(
                include_sdists=False,
                include_wheels=True,
                sdist_server_url=str(self.index_url),
                constraints=ctx.constraints,
                req_type=req_type,
                ignore_platform=False,
            )
        return self._resolver_provider_from_hook(
            hook=hook,
            ctx=ctx,
            req=req,
            req_type=req_type,
            sdist_server_url=str(self.index_url),
            include_sdists=False,
            include_wheels=True,
            ignore_platform=False,
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        version: Version,
        download_url: str,
    ) -> DownloadedSource:
        """Download a pre-built wheel via the ``download_source`` override hook."""
        return self._download_from_hook(
            ctx, req, version, download_url, DownloadKind.prebuilt_wheel
        )


SourceResolver = typing.Annotated[
    PyPISDistResolver
    | PyPIPrebuiltResolver
    | PyPIDownloadResolver
    | PyPIGitResolver
    | GitHubTagCloneResolver
    | GitHubTagDownloadResolver
    | GitLabTagCloneResolver
    | GitLabTagDownloadResolver
    | NotAvailableResolver
    | HookSDistResolver
    | HookPrebuiltResolver,
    pydantic.Field(..., discriminator="provider"),
]
