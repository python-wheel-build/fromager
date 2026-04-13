from __future__ import annotations

import enum
import logging
import re
import typing

import pydantic

from .. import resolver
from ._typedefs import MODEL_CONFIG, PackageVersion

if typing.TYPE_CHECKING:
    from .. import context, requirements_file

logger = logging.getLogger(__name__)

VERSION_QUOTED = "%7Bversion%7D"


class BuildSDist(enum.StrEnum):
    pep517 = "pep517"
    tarball = "tarball"


class AbstractResolver(pydantic.BaseModel):
    model_config = MODEL_CONFIG

    provider: str

    def resolver_provider(
        self, ctx: context.WorkContext, req_type: requirements_file.RequirementType
    ) -> resolver.BaseProvider:
        raise NotImplementedError


class PyPISDistResolver(AbstractResolver):
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

    index_url: pydantic.HttpUrl = pydantic.Field(
        default=pydantic.HttpUrl("https://pypi.org/simple/"),
        description="Python Package Index URL",
    )

    # It is not safe to use PEP 517 to re-generate a source distribution.
    # Some PEP 517 backends require VCS to generate correct sdist.
    build_sdist: typing.ClassVar[BuildSDist | None] = BuildSDist.tarball

    def resolver_provider(
        self, ctx: context.WorkContext, req_type: requirements_file.RequirementType
    ) -> resolver.PyPIProvider:
        return resolver.PyPIProvider(
            include_sdists=True,
            include_wheels=False,
            sdist_server_url=str(self.index_url),
            constraints=ctx.constraints,
            req_type=req_type,
            ignore_platform=False,
        )


class PyPIPrebuiltResolver(AbstractResolver):
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

    index_url: pydantic.HttpUrl = pydantic.Field(
        default=pydantic.HttpUrl("https://pypi.org/simple/"),
        description="Python Package Index URL",
    )

    build_sdist: typing.ClassVar[BuildSDist | None] = None

    def resolver_provider(
        self, ctx: context.WorkContext, req_type: requirements_file.RequirementType
    ) -> resolver.PyPIProvider:
        return resolver.PyPIProvider(
            include_sdists=False,
            include_wheels=True,
            sdist_server_url=str(self.index_url),
            constraints=ctx.constraints,
            req_type=req_type,
            ignore_platform=False,
        )


class PyPIDownloadResolver(AbstractResolver):
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

    index_url: pydantic.HttpUrl = pydantic.Field(
        default=pydantic.HttpUrl("https://pypi.org/simple/"),
        description="Python Package Index URL",
    )

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
        if VERSION_QUOTED not in value.path:
            raise ValueError(f"missing '{{version}}' in url {value}")
        return value

    def resolver_provider(
        self, ctx: context.WorkContext, req_type: requirements_file.RequirementType
    ) -> resolver.PyPIProvider:
        return resolver.PyPIProvider(
            include_sdists=True,
            include_wheels=True,
            sdist_server_url=str(self.index_url),
            constraints=ctx.constraints,
            req_type=req_type,
            ignore_platform=True,
            override_download_url=str(self.download_url).replace(
                VERSION_QUOTED, "{version}"
            ),
        )


class PyPIGitResolver(AbstractResolver):
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

    index_url: pydantic.HttpUrl = pydantic.Field(
        default=pydantic.HttpUrl("https://pypi.org/simple/"),
        description="Python Package Index URL",
    )

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
        self, ctx: context.WorkContext, req_type: requirements_file.RequirementType
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


class VersionMapResolver(AbstractResolver):
    """Maps known versions to git commits.

    The ``versionmap-git`` provider maps known version numbers to known git
    commits. It clones a git repo at the configured tag.

    Example::

        provider: versionmap-git
        clone_url: https://git.example/viking/viking.git
        versionmap:
            '1.0': abad1dea
            '1.1': refs/tags/1.1
    """

    provider: typing.Literal["versionmap-git"]

    clone_url: pydantic.AnyUrl
    """git clone URL

    https://git.test/repo.git
    """

    versionmap: dict[PackageVersion, str]

    build_sdist: typing.ClassVar[BuildSDist | None] = BuildSDist.tarball

    @pydantic.field_validator("clone_url", mode="after")
    @classmethod
    def validate_clone_url(cls, value: pydantic.AnyUrl) -> pydantic.AnyUrl:
        if value.scheme not in {"https", "ssh"}:
            raise ValueError(f"invalid scheme in url {value}")
        if not value.path:
            raise ValueError(f"url {value} has an empty path")
        return value


# matches versions like "v1.0" and "1.0"
DEFAULT_TAG_MATCHER = re.compile(r"^(v?\d.*)$")


class AbstractGitSourceResolver(AbstractResolver):
    """Common abstract class for GitHub and GitLab resolver"""

    project_url: pydantic.HttpUrl
    """Full project URL"""

    matcher_factory: pydantic.ImportString = DEFAULT_TAG_MATCHER
    """Matcher import string (``package.module:name``)

    Matcher can be a :class:`re.Pattern` object or a factory function
    that accepts *ctx* arg and returns a :class:`~fromager.resolver.MatchFunction`.
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
    def validate_matcher(
        cls, value: re.Pattern | typing.Callable
    ) -> re.Pattern | typing.Callable:
        """Validate that tag pattern has exactly one match group"""
        if isinstance(value, re.Pattern):
            if value.groups != 1:
                raise ValueError(
                    "Expected a re pattern with exactly one match group, "
                    f"got {value.groups} groups for {value.pattern}."
                )
        elif not callable(value):
            raise TypeError(f"{value} is not callable")
        return value

    def _get_matcher(
        self, ctx: context.WorkContext
    ) -> re.Pattern | resolver.MatchFunction:
        if isinstance(self.matcher_factory, re.Pattern):
            return self.matcher_factory
        elif callable(self.matcher_factory):
            return self.matcher_factory(ctx=ctx)  # type: ignore
        else:
            raise TypeError(self.matcher_factory)

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
        )

    def _gitlab_provider(
        self,
        *,
        ctx: context.WorkContext,
        req_type: requirements_file.RequirementType,
        override_download_url: str | None = None,
    ) -> resolver.GitLabTagProvider:
        assert self.project_url.path  # for type checker
        return resolver.GitLabTagProvider(
            project_path=self.project_url.path.lstrip("/"),
            server_url=f"https://{self.project_url.host}",
            constraints=ctx.constraints,
            matcher=self._get_matcher(ctx),
            req_type=req_type,
            override_download_url=override_download_url,
        )


class GitHubTagDownloadResolver(AbstractGitSourceResolver):
    """Resolve version from GitHub tags, build sdist from a git tarball download

    The ``github`` provider uses GitHub's REST API to resolve versions from tags.

    Example::

       provider: github-tag-download
       url: https://github.com/python-wheel-build/fromager
       matcher_factory: fromager.packagesettings:DEFAULT_TAG_MATCHER
       build_sdist: pep517
    """

    provider: typing.Literal["github-tag-download"]

    def resolver_provider(
        self, ctx: context.WorkContext, req_type: requirements_file.RequirementType
    ) -> resolver.GitHubTagProvider:
        return self._github_provider(
            ctx=ctx, req_type=req_type, override_download_url="FIXME"
        )


class GitHubTagCloneResolver(AbstractGitSourceResolver):
    """Resolve version from GitHub tags, build sdist from a git clone

    The ``github`` provider uses GitHub's REST API to resolve versions from tags.

    Example::

       provider: github-tag-git
       url: https://github.com/python-wheel-build/fromager
       matcher_factory: fromager.packagesettings:DEFAULT_TAG_MATCHER
       build_sdist: pep517
    """

    provider: typing.Literal["github-tag-git"]

    def resolver_provider(
        self, ctx: context.WorkContext, req_type: requirements_file.RequirementType
    ) -> resolver.GitHubTagProvider:
        return self._github_provider(
            ctx=ctx, req_type=req_type, override_download_url="FIXME"
        )


class GitLabTagDownloadResolver(AbstractGitSourceResolver):
    """Resolve version from GitLab tags, build sdist from a git tarball download

    The ``gitlab`` provider uses GitLab's REST API to resolve versions from tags.

    Example::

       provider: gitlab-tag-download
       url: https://gitlab.test/python-wheel-build/fromager
       matcher_factory: fromager.packagesettings:DEFAULT_TAG_MATCHER
       build_sdist: pep517
    """

    provider: typing.Literal["gitlab-tag-download"]

    def resolver_provider(
        self, ctx: context.WorkContext, req_type: requirements_file.RequirementType
    ) -> resolver.GitLabTagProvider:
        return self._gitlab_provider(
            ctx=ctx, req_type=req_type, override_download_url="FIXME"
        )


class GitLabTagCloneResolver(AbstractGitSourceResolver):
    """Resolve version from GitLab tags, build sdist from a git clone

    The ``gitlab`` provider uses GitLab's REST API to resolve versions from tags.

    Example::

       provider: gitlab-tag-git
       url: https://gitlab.test/python-wheel-build/fromager
       matcher_factory: fromager.packagesettings:DEFAULT_TAG_MATCHER
       build_sdist: pep517
    """

    provider: typing.Literal["gitlab-tag-git"]

    def resolver_provider(
        self, ctx: context.WorkContext, req_type: requirements_file.RequirementType
    ) -> resolver.GitLabTagProvider:
        return self._gitlab_provider(
            ctx=ctx, req_type=req_type, override_download_url="FIXME"
        )


class NotAvailableResolver(pydantic.BaseModel):
    """Prevent resolve and download"""

    model_config = MODEL_CONFIG

    provider: typing.Literal["not-available"]

    def resolver_provider(
        self, ctx: context.WorkContext, req_type: requirements_file.RequirementType
    ) -> resolver.BaseProvider:
        raise ValueError("package is not available")


class HookResolver(pydantic.BaseModel):
    """Call resolver_provider and download_source hook"""

    model_config = MODEL_CONFIG

    provider: typing.Literal["hook"]

    def resolver_provider(
        self, ctx: context.WorkContext, req_type: requirements_file.RequirementType
    ) -> resolver.BaseProvider:
        # TODO
        raise NotImplementedError


SourceResolver = (
    PyPISDistResolver
    | PyPIPrebuiltResolver
    | PyPIDownloadResolver
    | PyPIGitResolver
    | VersionMapResolver
    | GitHubTagCloneResolver
    | GitHubTagDownloadResolver
    | GitLabTagCloneResolver
    | GitLabTagDownloadResolver
    | NotAvailableResolver
    | HookResolver
)
