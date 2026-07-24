from __future__ import annotations

import datetime
import re
import textwrap
import typing
from unittest import mock

import pydantic
import pytest
import yaml
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import resolver
from fromager.candidate import Candidate, Cooldown
from fromager.context import WorkContext
from fromager.packagesettings._resolver import (
    BuildSDist,
    DownloadKind,
    GitHubTagCloneResolver,
    GitHubTagDownloadResolver,
    GitLabTagCloneResolver,
    GitLabTagDownloadResolver,
    HookPrebuiltResolver,
    HookSDistResolver,
    NotAvailableResolver,
    PyPIDownloadResolver,
    PyPIGitResolver,
    PyPIPrebuiltResolver,
    PyPISDistResolver,
    SourceResolver,
)
from fromager.packagesettings._typedefs import MODEL_CONFIG
from fromager.requirements_file import RequirementType


def _custom_matcher_factory(ctx: WorkContext) -> re.Pattern[str]:
    """Test matcher factory with the ``func(ctx)`` signature."""
    return re.compile(r"^(release-.+)$")


def _bad_matcher_returns_string(ctx: WorkContext) -> str:
    """Returns a string instead of a pattern or callable."""
    return "not a matcher"


def _bad_matcher_returns_no_groups(ctx: WorkContext) -> re.Pattern[str]:
    """Returns a pattern with no capture groups."""
    return re.compile(r"^v?\d.*$")


def _bad_matcher_returns_bad_sig(ctx: WorkContext) -> typing.Callable[..., None]:
    """Returns a callable with wrong signature."""

    def bad_func(x: str) -> None:
        return None

    return bad_func


_REQ = Requirement("test-pkg")
_REQ_TYPE = RequirementType.INSTALL
_VERSION = Version("1.2.3")
_CANDIDATE_SDIST = Candidate(
    name="test-pkg",
    version=_VERSION,
    url="https://pypi.test/packages/test-pkg-1.2.3.tar.gz",
    is_sdist=True,
)
_CANDIDATE_WHEEL = Candidate(
    name="test-pkg",
    version=_VERSION,
    url="https://pypi.test/packages/test_pkg-1.2.3-py3-none-any.whl",
    is_sdist=False,
)
_CANDIDATE_TARBALL = Candidate(
    name="test-pkg",
    version=_VERSION,
    url="https://download.test/test-pkg-1.2.3.tar.gz",
)
_CANDIDATE_GIT = Candidate(
    name="test-pkg",
    version=_VERSION,
    url="git+https://code.test/project/repo.git@refs/tags/v1.2.3",
)
_CANDIDATE_GITHUB_TARBALL = Candidate(
    name="test-pkg",
    version=_VERSION,
    url="https://api.github.com/repos/org/repo/tarball/v1.2.3",
    remote_tag="v1.2.3",
)
_CANDIDATE_GITHUB_CLONE = Candidate(
    name="test-pkg",
    version=_VERSION,
    url="git+https://github.com/python-wheel-build/fromager@v1.2.3",
    remote_tag="v1.2.3",
)
_CANDIDATE_GITLAB_TARBALL = Candidate(
    name="test-pkg",
    version=_VERSION,
    url="https://gitlab.test/group/project/-/archive/v1.2.3/project-v1.2.3.tar.gz",
    remote_tag="v1.2.3",
)
_CANDIDATE_GITLAB_CLONE = Candidate(
    name="test-pkg",
    version=_VERSION,
    url="git+https://gitlab.test/python-wheel-build/fromager@v1.2.3",
    remote_tag="v1.2.3",
)


class _SourceWrapper(pydantic.BaseModel):
    """Mirrors the ``source:`` key in a package settings YAML file."""

    model_config = MODEL_CONFIG
    source: SourceResolver


def _parse(raw_yaml: str) -> SourceResolver:
    """Parse a YAML string with a ``source:`` key into a resolver model."""
    data = yaml.safe_load(textwrap.dedent(raw_yaml))
    wrapper = _SourceWrapper.model_validate(data)
    return wrapper.source


# -- PyPI resolvers -----------------------------------------------------------


class TestPyPISDistResolver:
    YAML = """\
        source:
          provider: pypi-sdist
          index_url: https://pypi.test/simple
    """

    def test_parse(self) -> None:
        r = _parse(self.YAML)
        assert isinstance(r, PyPISDistResolver)
        assert r.provider == "pypi-sdist"
        assert str(r.index_url) == "https://pypi.test/simple"
        assert r.build_sdist == BuildSDist.tarball
        assert r.min_release_age is None
        assert r.supports_override_hooks is False
        assert r.resolves_prebuilt_wheel is False
        assert r.download_kinds == frozenset({DownloadKind.sdist})

    def test_default_index_url(self) -> None:
        r = PyPISDistResolver(provider="pypi-sdist")
        assert str(r.index_url) == "https://pypi.org/simple/"

    def test_cooldown_override(self) -> None:
        r = PyPISDistResolver(provider="pypi-sdist", min_release_age=7)
        assert r.min_release_age == 7

    def test_cooldown_disabled(self) -> None:
        r = PyPISDistResolver(provider="pypi-sdist", min_release_age=0)
        assert r.min_release_age == 0

    def test_resolver_provider(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        p = r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)
        assert isinstance(p, resolver.PyPIProvider)
        assert p.include_sdists is True
        assert p.include_wheels is False
        assert p.sdist_server_url == "https://pypi.test/simple"
        assert p.ignore_platform is False
        assert p.override_download_url is None
        assert p.cooldown is None

    def test_resolver_provider_cooldown(self, tmp_context: WorkContext) -> None:
        r = PyPISDistResolver(provider="pypi-sdist", min_release_age=7)
        p = r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)
        assert isinstance(p.cooldown, Cooldown)
        assert p.cooldown.min_age == datetime.timedelta(days=7)

    def test_resolver_provider_cooldown_disabled(
        self, tmp_context: WorkContext
    ) -> None:
        r = PyPISDistResolver(provider="pypi-sdist", min_release_age=0)
        p = r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)
        assert p.cooldown is None

    def test_cooldown_negative(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="min_release_age"):
            PyPISDistResolver(provider="pypi-sdist", min_release_age=-1)

    @mock.patch("fromager.downloads.download_sdist")
    def test_download(self, mock_dl: mock.MagicMock, tmp_context: WorkContext) -> None:
        expected = tmp_context.sdists_downloads / "test-pkg-1.2.3.tar.gz"
        mock_dl.return_value = expected
        r = _parse(self.YAML)
        path, kind = r.download(tmp_context, _REQ, _CANDIDATE_SDIST)
        assert path == expected
        assert kind is DownloadKind.sdist
        mock_dl.assert_called_once_with(
            destination_dir=tmp_context.sdists_downloads,
            url=_CANDIDATE_SDIST.url,
        )


class TestPyPIPrebuiltResolver:
    YAML = """\
        source:
          provider: pypi-prebuilt
          index_url: https://pypi.test/simple
    """

    def test_parse(self) -> None:
        r = _parse(self.YAML)
        assert isinstance(r, PyPIPrebuiltResolver)
        assert r.provider == "pypi-prebuilt"
        assert str(r.index_url) == "https://pypi.test/simple"
        assert r.build_sdist is None
        assert r.min_release_age is None
        assert r.supports_override_hooks is False
        assert r.resolves_prebuilt_wheel is True
        assert r.download_kinds == frozenset({DownloadKind.prebuilt_wheel})

    def test_resolver_provider(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        p = r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)
        assert isinstance(p, resolver.PyPIProvider)
        assert p.include_sdists is False
        assert p.include_wheels is True
        assert p.sdist_server_url == "https://pypi.test/simple"
        assert p.ignore_platform is False

    @mock.patch("fromager.downloads.download_wheel")
    def test_download(self, mock_dl: mock.MagicMock, tmp_context: WorkContext) -> None:
        expected = tmp_context.wheels_prebuilt / "test_pkg-1.2.3-py3-none-any.whl"
        mock_dl.return_value = expected
        r = _parse(self.YAML)
        path, kind = r.download(tmp_context, _REQ, _CANDIDATE_WHEEL)
        assert path == expected
        assert kind is DownloadKind.prebuilt_wheel
        mock_dl.assert_called_once_with(
            destination_dir=tmp_context.wheels_prebuilt,
            url=_CANDIDATE_WHEEL.url,
        )


class TestPyPIDownloadResolver:
    YAML = """\
        source:
          provider: pypi-download
          index_url: https://pypi.test/simple
          download_url: https://download.test/pkg-{version}.tar.gz
          download_kind: tarball
    """

    def test_parse(self) -> None:
        r = _parse(self.YAML)
        assert isinstance(r, PyPIDownloadResolver)
        assert r.provider == "pypi-download"
        assert str(r.index_url) == "https://pypi.test/simple"
        assert "%7Bversion%7D" in str(r.download_url)
        assert r.build_sdist == BuildSDist.tarball
        assert r.min_release_age is None
        assert r.supports_override_hooks is False
        assert r.resolves_prebuilt_wheel is False
        assert r.download_kind == DownloadKind.tarball
        assert r.download_kinds == frozenset({DownloadKind.sdist, DownloadKind.tarball})

    def test_download_kind_sdist(self) -> None:
        r = _parse("""\
            source:
              provider: pypi-download
              download_url: https://download.test/pkg-{version}.tar.gz
              download_kind: sdist
        """)
        assert isinstance(r, PyPIDownloadResolver)
        assert r.download_kind == DownloadKind.sdist

    def test_download_kind_rejects_invalid(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="download_kind"):
            _parse("""\
                source:
                  provider: pypi-download
                  download_url: https://download.test/pkg-{version}.tar.gz
                  download_kind: prebuilt_wheel
            """)

    def test_resolver_provider(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        p = r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)
        assert isinstance(p, resolver.PyPIProvider)
        assert p.include_sdists is True
        assert p.include_wheels is True
        assert p.sdist_server_url == "https://pypi.test/simple"
        assert p.ignore_platform is True
        assert p.override_download_url == ("https://download.test/pkg-{version}.tar.gz")

    def test_missing_version_template(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="version"):
            PyPIDownloadResolver(
                provider="pypi-download",
                download_url="https://download.test/pkg-latest.tar.gz",  # type: ignore[arg-type]
                download_kind=DownloadKind.tarball,
            )

    @mock.patch("fromager.downloads.download_url")
    def test_download(self, mock_dl: mock.MagicMock, tmp_context: WorkContext) -> None:
        expected = tmp_context.sdists_downloads / "test-pkg-1.2.3.tar.gz"
        mock_dl.return_value = expected
        r = _parse(self.YAML)
        path, kind = r.download(tmp_context, _REQ, _CANDIDATE_TARBALL)
        assert path == expected
        assert kind is DownloadKind.tarball
        mock_dl.assert_called_once_with(
            destination_dir=tmp_context.sdists_downloads,
            url=_CANDIDATE_TARBALL.url,
            destination_filename="test-pkg-1.2.3.tar.gz",
        )


class TestPyPIGitResolver:
    YAML = """\
        source:
          provider: pypi-git
          index_url: https://pypi.test/simple
          clone_url: https://github.com/python-wheel-build/fromager.git
          tag: 'v{version}'
    """

    def test_parse(self) -> None:
        r = _parse(self.YAML)
        assert isinstance(r, PyPIGitResolver)
        assert r.provider == "pypi-git"
        assert str(r.index_url) == "https://pypi.test/simple"
        assert str(r.clone_url) == (
            "https://github.com/python-wheel-build/fromager.git"
        )
        assert r.tag == "v{version}"
        assert r.build_sdist == BuildSDist.pep517
        assert r.min_release_age is None
        assert r.supports_override_hooks is False
        assert r.resolves_prebuilt_wheel is False
        assert r.download_kinds == frozenset({DownloadKind.git_checkout})

    def test_resolver_provider(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        p = r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)
        assert isinstance(p, resolver.PyPIProvider)
        assert p.include_sdists is True
        assert p.include_wheels is True
        assert p.sdist_server_url == "https://pypi.test/simple"
        assert p.ignore_platform is True
        assert p.override_download_url == (
            "git+https://github.com/python-wheel-build/fromager.git"
            "@refs/tags/v{version}"
        )

    def test_missing_version_in_tag(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="version"):
            PyPIGitResolver(
                provider="pypi-git",
                clone_url="https://github.com/org/repo.git",  # type: ignore[arg-type]
                tag="latest",
            )

    def test_clone_url_rejects_http(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            PyPIGitResolver(
                provider="pypi-git",
                clone_url="http://github.com/org/repo.git",  # type: ignore[arg-type]
                tag="v{version}",
            )

    @mock.patch("fromager.downloads.download_git_source")
    def test_download(self, mock_dl: mock.MagicMock, tmp_context: WorkContext) -> None:
        expected_dest = (
            tmp_context.work_dir / f"{_REQ.name}-{_VERSION}" / f"{_REQ.name}-{_VERSION}"
        )
        mock_dl.return_value = expected_dest
        r = _parse(self.YAML)
        path, kind = r.download(tmp_context, _REQ, _CANDIDATE_GIT)
        assert path == expected_dest
        assert kind is DownloadKind.git_checkout
        mock_dl.assert_called_once_with(
            destination_dir=expected_dest,
            vcs_url=_CANDIDATE_GIT.url,
        )


# -- Git source resolvers ----------------------------------------------------


class TestGitHubTagDownloadResolver:
    YAML = """\
        source:
          provider: github-tag-download
          project_url: https://github.com/python-wheel-build/fromager
    """

    def test_parse(self) -> None:
        r = _parse(self.YAML)
        assert isinstance(r, GitHubTagDownloadResolver)
        assert r.provider == "github-tag-download"
        assert str(r.project_url) == ("https://github.com/python-wheel-build/fromager")
        assert callable(r.matcher_factory)
        assert r.build_sdist == BuildSDist.pep517
        assert r.min_release_age is None
        assert r.supports_override_hooks is False
        assert r.resolves_prebuilt_wheel is False
        assert r.download_kinds == frozenset({DownloadKind.tarball})

    def test_explicit_matcher_factory(self) -> None:
        r = _parse("""\
            source:
              provider: github-tag-download
              project_url: https://github.com/python-wheel-build/fromager
              matcher_factory: tests.test_packagesettings_resolver:_custom_matcher_factory
        """)
        assert isinstance(r, GitHubTagDownloadResolver)
        assert callable(r.matcher_factory)
        assert r.matcher_factory.__name__ == "_custom_matcher_factory"

    def test_cooldown_override(self) -> None:
        r = GitHubTagDownloadResolver(
            provider="github-tag-download",
            project_url="https://github.com/python-wheel-build/fromager",  # type: ignore[arg-type]
            min_release_age=14,
        )
        assert r.min_release_age == 14

    def test_project_url_rejects_http(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="https"):
            GitHubTagDownloadResolver(
                provider="github-tag-download",
                project_url="http://github.com/org/repo",  # type: ignore[arg-type]
            )

    def test_resolver_provider(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        p = r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)
        assert isinstance(p, resolver.GitHubTagProvider)
        assert p.organization == "python-wheel-build"
        assert p.repo == "fromager"
        assert p.override_download_url is None
        assert p.cooldown is None

    def test_resolver_provider_cooldown(self, tmp_context: WorkContext) -> None:
        r = GitHubTagDownloadResolver(
            provider="github-tag-download",
            project_url="https://github.com/python-wheel-build/fromager",  # type: ignore[arg-type]
            min_release_age=14,
        )
        p = r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)
        assert isinstance(p.cooldown, Cooldown)
        assert p.cooldown.min_age == datetime.timedelta(days=14)

    def test_matcher_factory_rejects_non_callable_return(
        self, tmp_context: WorkContext
    ) -> None:
        r = GitHubTagDownloadResolver(
            provider="github-tag-download",
            project_url="https://github.com/python-wheel-build/fromager",  # type: ignore[arg-type]
            matcher_factory=_bad_matcher_returns_string,  # type: ignore[arg-type]
        )
        with pytest.raises(TypeError, match=r"expected re\.Pattern or callable"):
            r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)

    def test_matcher_factory_rejects_no_groups(self, tmp_context: WorkContext) -> None:
        r = GitHubTagDownloadResolver(
            provider="github-tag-download",
            project_url="https://github.com/python-wheel-build/fromager",  # type: ignore[arg-type]
            matcher_factory=_bad_matcher_returns_no_groups,  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="exactly one match group"):
            r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)

    def test_matcher_factory_rejects_bad_signature(
        self, tmp_context: WorkContext
    ) -> None:
        r = GitHubTagDownloadResolver(
            provider="github-tag-download",
            project_url="https://github.com/python-wheel-build/fromager",  # type: ignore[arg-type]
            matcher_factory=_bad_matcher_returns_bad_sig,  # type: ignore[arg-type]
        )
        with pytest.raises(TypeError, match=r"identifier.*item"):
            r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)

    def test_project_url_rejects_dot_git(self) -> None:
        with pytest.raises(pydantic.ValidationError, match=r"\.git"):
            GitHubTagDownloadResolver(
                provider="github-tag-download",
                project_url="https://github.com/org/repo.git",  # type: ignore[arg-type]
            )

    @mock.patch("fromager.downloads.download_url")
    def test_download(self, mock_dl: mock.MagicMock, tmp_context: WorkContext) -> None:
        expected = tmp_context.sdists_downloads / "test-pkg-1.2.3.tar.gz"
        mock_dl.return_value = expected
        r = _parse(self.YAML)
        path, kind = r.download(tmp_context, _REQ, _CANDIDATE_GITHUB_TARBALL)
        assert path == expected
        assert kind is DownloadKind.tarball
        mock_dl.assert_called_once_with(
            destination_dir=tmp_context.sdists_downloads,
            url=_CANDIDATE_GITHUB_TARBALL.url,
            destination_filename="test-pkg-1.2.3.tar.gz",
        )


class TestGitHubTagCloneResolver:
    YAML = """\
        source:
          provider: github-tag-git
          project_url: https://github.com/python-wheel-build/fromager
    """

    def test_parse(self) -> None:
        r = _parse(self.YAML)
        assert isinstance(r, GitHubTagCloneResolver)
        assert r.provider == "github-tag-git"
        assert str(r.project_url) == "https://github.com/python-wheel-build/fromager"
        assert callable(r.matcher_factory)
        assert r.build_sdist == BuildSDist.pep517
        assert r.min_release_age is None
        assert r.supports_override_hooks is False
        assert r.resolves_prebuilt_wheel is False
        assert r.download_kinds == frozenset({DownloadKind.git_checkout})

    def test_resolver_provider(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        p = r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)
        assert isinstance(p, resolver.GitHubTagProvider)
        assert p.organization == "python-wheel-build"
        assert p.repo == "fromager"
        assert p.override_download_url == (
            "git+https://github.com/python-wheel-build/fromager@{tagname}"
        )

    @mock.patch("fromager.downloads.download_git_source")
    def test_download(self, mock_dl: mock.MagicMock, tmp_context: WorkContext) -> None:
        expected_dest = (
            tmp_context.work_dir / f"{_REQ.name}-{_VERSION}" / f"{_REQ.name}-{_VERSION}"
        )
        mock_dl.return_value = expected_dest
        r = _parse(self.YAML)
        path, kind = r.download(tmp_context, _REQ, _CANDIDATE_GITHUB_CLONE)
        assert path == expected_dest
        assert kind is DownloadKind.git_checkout
        mock_dl.assert_called_once_with(
            destination_dir=expected_dest,
            vcs_url=_CANDIDATE_GITHUB_CLONE.url,
        )


class TestGitLabTagDownloadResolver:
    YAML = """\
        source:
          provider: gitlab-tag-download
          project_url: https://gitlab.test/python-wheel-build/fromager
    """

    def test_parse(self) -> None:
        r = _parse(self.YAML)
        assert isinstance(r, GitLabTagDownloadResolver)
        assert r.provider == "gitlab-tag-download"
        assert str(r.project_url) == "https://gitlab.test/python-wheel-build/fromager"
        assert callable(r.matcher_factory)
        assert r.build_sdist == BuildSDist.pep517
        assert r.min_release_age is None
        assert r.supports_override_hooks is False
        assert r.resolves_prebuilt_wheel is False
        assert r.download_kinds == frozenset({DownloadKind.tarball})

    def test_resolver_provider(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        p = r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)
        assert isinstance(p, resolver.GitLabTagProvider)
        assert p.project_path == "python-wheel-build/fromager"
        assert "gitlab.test" in p.server_url
        assert p.override_download_url is None

    @mock.patch("fromager.downloads.download_url")
    def test_download(self, mock_dl: mock.MagicMock, tmp_context: WorkContext) -> None:
        expected = tmp_context.sdists_downloads / "test-pkg-1.2.3.tar.gz"
        mock_dl.return_value = expected
        r = _parse(self.YAML)
        path, kind = r.download(tmp_context, _REQ, _CANDIDATE_GITLAB_TARBALL)
        assert path == expected
        assert kind is DownloadKind.tarball
        mock_dl.assert_called_once_with(
            destination_dir=tmp_context.sdists_downloads,
            url=_CANDIDATE_GITLAB_TARBALL.url,
            destination_filename="test-pkg-1.2.3.tar.gz",
        )


class TestGitLabTagCloneResolver:
    YAML = """\
        source:
          provider: gitlab-tag-git
          project_url: https://gitlab.test/python-wheel-build/fromager
    """

    def test_parse(self) -> None:
        r = _parse(self.YAML)
        assert isinstance(r, GitLabTagCloneResolver)
        assert r.provider == "gitlab-tag-git"
        assert str(r.project_url) == "https://gitlab.test/python-wheel-build/fromager"
        assert callable(r.matcher_factory)
        assert r.build_sdist == BuildSDist.pep517
        assert r.min_release_age is None
        assert r.supports_override_hooks is False
        assert r.resolves_prebuilt_wheel is False
        assert r.download_kinds == frozenset({DownloadKind.git_checkout})

    def test_resolver_provider(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        p = r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)
        assert isinstance(p, resolver.GitLabTagProvider)
        assert p.project_path == "python-wheel-build/fromager"
        assert "gitlab.test" in p.server_url
        assert p.override_download_url == (
            "git+https://gitlab.test/python-wheel-build/fromager@{tagname}"
        )

    @mock.patch("fromager.downloads.download_git_source")
    def test_download(self, mock_dl: mock.MagicMock, tmp_context: WorkContext) -> None:
        expected_dest = (
            tmp_context.work_dir / f"{_REQ.name}-{_VERSION}" / f"{_REQ.name}-{_VERSION}"
        )
        mock_dl.return_value = expected_dest
        r = _parse(self.YAML)
        path, kind = r.download(tmp_context, _REQ, _CANDIDATE_GITLAB_CLONE)
        assert path == expected_dest
        assert kind is DownloadKind.git_checkout
        mock_dl.assert_called_once_with(
            destination_dir=expected_dest,
            vcs_url=_CANDIDATE_GITLAB_CLONE.url,
        )


# -- Special resolvers --------------------------------------------------------


class TestNotAvailableResolver:
    YAML = """\
        source:
          provider: not-available
    """

    def test_parse(self) -> None:
        r = _parse(self.YAML)
        assert isinstance(r, NotAvailableResolver)
        assert r.provider == "not-available"
        assert r.supports_override_hooks is False
        assert r.resolves_prebuilt_wheel is False
        assert r.download_kinds == frozenset()

    def test_resolver_provider(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        with pytest.raises(ValueError, match="not available"):
            r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)

    def test_download(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        with pytest.raises(ValueError, match="not available"):
            r.download(tmp_context, _REQ, _CANDIDATE_SDIST)


class TestHookSDistResolver:
    YAML = """\
        source:
          provider: hook-sdist
    """

    def test_parse(self) -> None:
        r = _parse(self.YAML)
        assert isinstance(r, HookSDistResolver)
        assert r.provider == "hook-sdist"
        assert r.supports_override_hooks is True
        assert r.resolves_prebuilt_wheel is False
        assert r.download_kinds == frozenset(
            {DownloadKind.sdist, DownloadKind.tarball, DownloadKind.git_checkout}
        )

    def test_resolver_provider(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        with pytest.raises(NotImplementedError):
            r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)

    def test_download(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        with pytest.raises(NotImplementedError, match="hook"):
            r.download(tmp_context, _REQ, _CANDIDATE_SDIST)


class TestHookPrebuiltResolver:
    YAML = """\
        source:
          provider: hook-prebuilt
    """

    def test_parse(self) -> None:
        r = _parse(self.YAML)
        assert isinstance(r, HookPrebuiltResolver)
        assert r.provider == "hook-prebuilt"
        assert r.supports_override_hooks is True
        assert r.resolves_prebuilt_wheel is True
        assert r.download_kinds == frozenset({DownloadKind.prebuilt_wheel})

    def test_resolver_provider(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        with pytest.raises(NotImplementedError):
            r.resolver_provider(tmp_context, _REQ, _REQ_TYPE)

    def test_download(self, tmp_context: WorkContext) -> None:
        r = _parse(self.YAML)
        with pytest.raises(NotImplementedError, match="hook"):
            r.download(tmp_context, _REQ, _CANDIDATE_WHEEL)


# -- Discriminated union validation -------------------------------------------


def test_invalid_provider() -> None:
    with pytest.raises(pydantic.ValidationError):
        _parse("""\
            source:
              provider: nonexistent
        """)


def test_missing_provider() -> None:
    with pytest.raises(pydantic.ValidationError):
        _parse("""\
            source:
              index_url: https://pypi.test/simple
        """)
