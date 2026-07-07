from __future__ import annotations

import datetime
import enum
import inspect
import logging
import pathlib
import re
import typing

import pydantic

from .. import downloads, resolver
from ..candidate import Cooldown
from ._typedefs import MODEL_CONFIG

if typing.TYPE_CHECKING:
    from packaging.requirements import Requirement

    from .. import context, requirements_file
    from ..candidate import Candidate

logger = logging.getLogger(__name__)

_VERSION_QUOTED = "%7Bversion%7D"


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


class AbstractResolver(pydantic.BaseModel):
    """Abstract base class for resolvers"""

    model_config = MODEL_CONFIG

    provider: str

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
        req_type: requirements_file.RequirementType,
    ) -> resolver.BaseProvider:
        """Return a resolver provider for the given requirement."""
        raise NotImplementedError

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        candidate: Candidate,
    ) -> tuple[pathlib.Path, DownloadKind]:
        """Download the resolved artifact for *candidate*."""
        raise NotImplementedError

    def _download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        candidate: Candidate,
        download_kind: DownloadKind,
    ) -> tuple[pathlib.Path, DownloadKind]:
        """Download the resolved artifact for *candidate*.

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
                    url=candidate.url,
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
                    url=candidate.url,
                    destination_filename=(
                        f"{candidate.name}-{candidate.version}.tar.gz"
                    ),
                )
            case DownloadKind.prebuilt_wheel:
                destination_dir = ctx.wheels_prebuilt
                path = downloads.download_wheel(
                    destination_dir=destination_dir,
                    url=candidate.url,
                )
            case DownloadKind.git_checkout:
                # TODO: Maybe use dedicated directory like
                # 'work_dir / f"{name}-{version}" / "checkout"' for
                # checkout, generate a proper sdist, then unpack to
                # final destination?
                destination_dir = (
                    ctx.work_dir
                    / f"{req.name}-{candidate.version}"
                    / f"{req.name}-{candidate.version}"
                )
                path = downloads.download_git_source(
                    destination_dir=destination_dir,
                    vcs_url=candidate.url,
                )
            case _:  # includes any_source and not_available
                typing.assert_never(download_kind)  # type: ignore[arg-type]
        return path, download_kind


class CooldownMixin(pydantic.BaseModel):
    min_release_age: int | None = pydantic.Field(default=None, ge=0)
    """Minimum release age override in days.

    None (default): inherit the global ``--min-release-age`` setting.
    0: disable the release-age cooldown for this package.
    Positive integer: override the cooldown with this many days.
    """

    @property
    def _cooldown(self) -> Cooldown | None:
        """Convert ``min_release_age`` to a ``Cooldown`` instance."""
        if not self.min_release_age:
            return None
        return Cooldown(min_age=datetime.timedelta(days=self.min_release_age))


class AbstractPyPIResolver(AbstractResolver, CooldownMixin):
    """Abstract base class for PyPI resolvers"""

    index_url: pydantic.HttpUrl = pydantic.Field(
        default=pydantic.HttpUrl("https://pypi.org/simple/"),
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
    build_sdist: typing.ClassVar[BuildSDist | None] = BuildSDist.tarball
    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset({DownloadKind.sdist})

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType,
    ) -> resolver.PyPIProvider:
        return resolver.PyPIProvider(
            include_sdists=True,
            include_wheels=False,
            sdist_server_url=str(self.index_url),
            constraints=ctx.constraints,
            req_type=req_type,
            ignore_platform=False,
            cooldown=self._cooldown,
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        candidate: Candidate,
    ) -> tuple[pathlib.Path, DownloadKind]:
        """Download an sdist from PyPI."""
        return self._download(ctx, req, candidate, DownloadKind.sdist)


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

    build_sdist: typing.ClassVar[BuildSDist | None] = None
    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset(
        {DownloadKind.prebuilt_wheel}
    )
    resolves_prebuilt_wheel: typing.ClassVar[bool] = True

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType,
    ) -> resolver.PyPIProvider:
        return resolver.PyPIProvider(
            include_sdists=False,
            include_wheels=True,
            sdist_server_url=str(self.index_url),
            constraints=ctx.constraints,
            req_type=req_type,
            ignore_platform=False,
            cooldown=self._cooldown,
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        candidate: Candidate,
    ) -> tuple[pathlib.Path, DownloadKind]:
        """Download a pre-built wheel from PyPI."""
        return self._download(ctx, req, candidate, DownloadKind.prebuilt_wheel)


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

    build_sdist: typing.ClassVar[BuildSDist | None] = BuildSDist.tarball
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
        req_type: requirements_file.RequirementType,
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
            cooldown=self._cooldown,
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        candidate: Candidate,
    ) -> tuple[pathlib.Path, DownloadKind]:
        """Download an sdist or tarball from a custom URL."""
        return self._download(ctx, req, candidate, self.download_kind)


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
        req_type: requirements_file.RequirementType,
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
            cooldown=self._cooldown,
        )

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        candidate: Candidate,
    ) -> tuple[pathlib.Path, DownloadKind]:
        """Clone a git repository at a specific tag."""
        return self._download(ctx, req, candidate, DownloadKind.git_checkout)


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
        req_type: requirements_file.RequirementType,
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
            cooldown=self._cooldown,
        )

    def _gitlab_provider(
        self,
        *,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType,
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
            cooldown=self._cooldown,
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
        req_type: requirements_file.RequirementType,
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
        candidate: Candidate,
    ) -> tuple[pathlib.Path, DownloadKind]:
        """Download a tarball from a GitHub tag."""
        return self._download(ctx, req, candidate, DownloadKind.tarball)


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
        req_type: requirements_file.RequirementType,
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
        candidate: Candidate,
    ) -> tuple[pathlib.Path, DownloadKind]:
        """Clone a git repository from a GitHub tag."""
        return self._download(ctx, req, candidate, DownloadKind.git_checkout)


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
        req_type: requirements_file.RequirementType,
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
        candidate: Candidate,
    ) -> tuple[pathlib.Path, DownloadKind]:
        """Download a tarball from a GitLab tag."""
        return self._download(ctx, req, candidate, DownloadKind.tarball)


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
        req_type: requirements_file.RequirementType,
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
        candidate: Candidate,
    ) -> tuple[pathlib.Path, DownloadKind]:
        """Clone a git repository from a GitLab tag."""
        return self._download(ctx, req, candidate, DownloadKind.git_checkout)


class NotAvailableResolver(AbstractResolver):
    """Prevent resolve and download"""

    provider: typing.Literal["not-available"]

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType,
    ) -> resolver.BaseProvider:
        raise ValueError(f"package {req.name} is not available")

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        candidate: Candidate,
    ) -> tuple[pathlib.Path, DownloadKind]:
        """Raise because package is not available."""
        raise ValueError(f"package {req.name} is not available")


class AbstractHookResolver(AbstractResolver, CooldownMixin):
    """Abstract base class for hook-based resolvers"""

    supports_override_hooks: typing.ClassVar[bool] = True
    """Hook resolvers support override hooks."""

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        req_type: requirements_file.RequirementType,
    ) -> resolver.BaseProvider:
        # TODO
        raise NotImplementedError("Hook resolver needs a hook")

    def download(
        self,
        ctx: context.WorkContext,
        req: Requirement,
        candidate: Candidate,
    ) -> tuple[pathlib.Path, DownloadKind]:
        """Raise because hook-based download is not yet implemented."""
        raise NotImplementedError("Hook resolver download needs a hook")


class HookSDistResolver(AbstractHookResolver):
    """Call resolver_provider and download_source hook, build from source

    The ``hook-sdist`` provider delegates resolution and download to
    plugin hooks. The downloaded artifact can be a source distribution,
    a tarball, or a git checkout.

    Example::

        provider: hook-sdist
    """

    provider: typing.Literal["hook-sdist"]

    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset(
        {DownloadKind.sdist, DownloadKind.tarball, DownloadKind.git_checkout}
    )


class HookPrebuiltResolver(AbstractHookResolver):
    """Call resolver_provider and download_source hook, use pre-built wheel

    The ``hook-prebuilt`` provider delegates resolution and download to
    plugin hooks. The downloaded artifact must be a pre-built wheel.

    Example::

        provider: hook-prebuilt
    """

    provider: typing.Literal["hook-prebuilt"]

    download_kinds: typing.ClassVar[DownloadKindSet] = frozenset(
        {DownloadKind.prebuilt_wheel}
    )
    resolves_prebuilt_wheel: typing.ClassVar[bool] = True


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
