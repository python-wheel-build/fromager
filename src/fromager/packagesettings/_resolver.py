from __future__ import annotations

import datetime
import enum
import inspect
import logging
import re
import typing

import pydantic

from .. import resolver
from ..candidate import Cooldown
from ._typedefs import MODEL_CONFIG

if typing.TYPE_CHECKING:
    from .. import context, requirements_file

logger = logging.getLogger(__name__)

_VERSION_QUOTED = "%7Bversion%7D"


class BuildSDist(enum.StrEnum):
    pep517 = "pep517"
    tarball = "tarball"


class AbstractResolver(pydantic.BaseModel):
    """Abstract base class for resolvers"""

    model_config = MODEL_CONFIG

    provider: str

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType | None = None,
    ) -> resolver.BaseProvider:
        raise NotImplementedError


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

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType | None = None,
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

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType | None = None,
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
    """

    provider: typing.Literal["pypi-download"]

    download_url: pydantic.HttpUrl
    """Remote download URL

    URL must contain '{version}' template string.
    """

    build_sdist: typing.ClassVar[BuildSDist | None] = BuildSDist.tarball

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
        req_type: requirements_file.RequirementType | None = None,
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

    clone_url: pydantic.AnyUrl
    """git clone URL

    https://git.test/repo.git
    """

    tag: str

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

    @pydantic.field_validator("tag", mode="after")
    @classmethod
    def validate_tag(cls, value: str) -> str:
        if "{version}" not in value:
            raise ValueError(f"missing '{{version}}' in tag {value}")
        return value

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType | None = None,
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
        req_type: requirements_file.RequirementType | None = None,
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
        req_type: requirements_file.RequirementType | None = None,
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

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType | None = None,
    ) -> resolver.GitHubTagProvider:
        return self._github_provider(
            ctx=ctx,
            req_type=req_type,
            override_download_url=None,
        )


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

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType | None = None,
    ) -> resolver.GitHubTagProvider:
        return self._github_provider(
            ctx=ctx,
            req_type=req_type,
            override_download_url=f"git+{self.project_url}@{{tagname}}",
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

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType | None = None,
    ) -> resolver.GitLabTagProvider:
        return self._gitlab_provider(
            ctx=ctx,
            req_type=req_type,
            override_download_url=None,
        )


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

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType | None = None,
    ) -> resolver.GitLabTagProvider:
        return self._gitlab_provider(
            ctx=ctx,
            req_type=req_type,
            override_download_url=f"git+{self.project_url}@{{tagname}}",
        )


class NotAvailableResolver(AbstractResolver):
    """Prevent resolve and download"""

    provider: typing.Literal["not-available"]

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType | None = None,
    ) -> resolver.BaseProvider:
        raise ValueError("package is not available")


class HookResolver(AbstractResolver):
    """Call resolver_provider and download_source hook"""

    provider: typing.Literal["hook"]

    def resolver_provider(
        self,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType | None = None,
    ) -> resolver.BaseProvider:
        # TODO
        raise NotImplementedError("Hook resolver needs a hook")


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
    | HookResolver,
    pydantic.Field(..., discriminator="provider"),
]
