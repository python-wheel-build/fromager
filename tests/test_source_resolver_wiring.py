"""Tests for wiring source resolver configuration into the runtime.

Covers:
- ``PackageBuildInfo.source_resolver`` property
- source resolver dispatch (source config takes priority over plugins)
- ``default_download_source()`` handling ``git+`` URLs
- ``download_git_source()`` honouring ``remove_dot_git``
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

from packaging.requirements import Requirement
from packaging.version import Version

from fromager import context, packagesettings, resolver, sources
from fromager.requirements_file import RequirementType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context_with_source(
    tmp_path: pathlib.Path,
    source_yaml: dict,
    *,
    variant: str = "cpu",
    variant_source_yaml: dict | None = None,
    git_options: dict | None = None,
) -> context.WorkContext:
    """Create a ``WorkContext`` whose test-pkg has a ``source`` field."""
    pkg_config: dict = {"source": source_yaml}
    if variant_source_yaml is not None:
        pkg_config["variants"] = {variant: {"source": variant_source_yaml}}
    if git_options is not None:
        pkg_config["git_options"] = git_options

    settings_file = packagesettings.SettingsFile()
    ps = packagesettings.PackageSettings.from_mapping(
        "test-pkg",
        pkg_config,
        source="test",
        has_config=True,
    )
    settings = packagesettings.Settings(
        settings=settings_file,
        package_settings=[ps],
        patches_dir=tmp_path / "patches",
        variant=variant,
        max_jobs=None,
    )
    ctx = context.WorkContext(
        active_settings=settings,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
    )
    ctx.setup()
    return ctx


# ---------------------------------------------------------------------------
# PackageBuildInfo.source_resolver
# ---------------------------------------------------------------------------


class TestSourceResolverProperty:
    def test_no_source_returns_none(self, tmp_context: context.WorkContext) -> None:
        req = Requirement("some-pkg")
        pbi = tmp_context.package_build_info(req)
        assert pbi.source_resolver is None

    def test_package_level_source(self, tmp_path: pathlib.Path) -> None:
        ctx = _make_context_with_source(
            tmp_path,
            {"provider": "pypi-sdist", "index_url": "https://pypi.test/simple"},
        )
        req = Requirement("test-pkg")
        pbi = ctx.package_build_info(req)
        assert pbi.source_resolver is not None
        assert pbi.source_resolver.provider == "pypi-sdist"

    def test_variant_overrides_package(self, tmp_path: pathlib.Path) -> None:
        ctx = _make_context_with_source(
            tmp_path,
            {"provider": "pypi-sdist"},
            variant_source_yaml={
                "provider": "pypi-prebuilt",
                "index_url": "https://wheels.test/simple",
            },
        )
        req = Requirement("test-pkg")
        pbi = ctx.package_build_info(req)
        sr = pbi.source_resolver
        assert sr is not None
        assert sr.provider == "pypi-prebuilt"

    def test_variant_without_source_falls_back_to_package(
        self, tmp_path: pathlib.Path
    ) -> None:
        ctx = _make_context_with_source(
            tmp_path,
            {"provider": "pypi-sdist"},
        )
        req = Requirement("test-pkg")
        pbi = ctx.package_build_info(req)
        assert pbi.source_resolver is not None
        assert pbi.source_resolver.provider == "pypi-sdist"


# ---------------------------------------------------------------------------
# Source resolver dispatch (source config takes priority over plugins)
# ---------------------------------------------------------------------------


class TestSourceResolverDispatch:
    def test_source_config_produces_correct_provider(
        self, tmp_path: pathlib.Path
    ) -> None:
        ctx = _make_context_with_source(
            tmp_path,
            {
                "provider": "pypi-sdist",
                "index_url": "https://custom.test/simple",
            },
        )
        req = Requirement("test-pkg")
        provider = sources.get_source_provider(
            ctx=ctx,
            req=req,
            sdist_server_url="https://pypi.test/simple/",
            req_type=RequirementType.INSTALL,
        )
        assert isinstance(provider, resolver.PyPIProvider)
        assert provider.sdist_server_url == "https://custom.test/simple"

    def test_falls_back_to_pypi_when_no_source(
        self, tmp_context: context.WorkContext
    ) -> None:
        req = Requirement("unknown-pkg")
        provider = sources.get_source_provider(
            ctx=tmp_context,
            req=req,
            sdist_server_url="https://pypi.test/simple/",
            req_type=RequirementType.INSTALL,
        )
        assert isinstance(provider, resolver.PyPIProvider)
        assert provider.sdist_server_url == "https://pypi.test/simple/"

    def test_github_tag_resolver_produces_github_provider(
        self, tmp_path: pathlib.Path
    ) -> None:
        ctx = _make_context_with_source(
            tmp_path,
            {
                "provider": "github-tag-download",
                "project_url": "https://github.com/python-wheel-build/fromager",
            },
        )
        req = Requirement("test-pkg")
        provider = sources.get_source_provider(
            ctx=ctx,
            req=req,
            sdist_server_url="https://pypi.test/simple/",
            req_type=RequirementType.INSTALL,
        )
        assert isinstance(provider, resolver.GitHubTagProvider)
        assert provider.organization == "python-wheel-build"
        assert provider.repo == "fromager"


# ---------------------------------------------------------------------------
# default_download_source with git URLs
# ---------------------------------------------------------------------------


class TestDefaultDownloadSourceGitUrl:
    @patch("fromager.sources.gitutils.git_clone_fast")
    def test_routes_git_url_to_git_clone_fast(
        self,
        mock_clone_fast: MagicMock,
        tmp_context: context.WorkContext,
    ) -> None:
        req = Requirement("test-pkg==1.0")
        version = Version("1.0")
        git_url = "git+https://github.test/org/repo.git@refs/tags/v1.0"

        result = sources.default_download_source(
            tmp_context,
            req,
            version,
            git_url,
            tmp_context.sdists_downloads,
        )

        mock_clone_fast.assert_called_once_with(
            output_dir=result,
            repo_url="https://github.test/org/repo.git",
            ref="refs/tags/v1.0",
        )
        assert result.name == "test-pkg-1.0"

    @patch("fromager.sources._download_source_check")
    def test_non_git_url_downloads_tarball(
        self,
        mock_check: MagicMock,
        tmp_context: context.WorkContext,
    ) -> None:
        req = Requirement("test-pkg==1.0")
        version = Version("1.0")
        tarball_url = "https://packages.test/test-pkg-1.0.tar.gz"
        mock_check.return_value = pathlib.Path("test-pkg-1.0.tar.gz")

        sources.default_download_source(
            tmp_context,
            req,
            version,
            tarball_url,
            tmp_context.sdists_downloads,
        )

        mock_check.assert_called_once()
        assert mock_check.call_args[1]["url"] == tarball_url


# ---------------------------------------------------------------------------
# download_git_source + remove_dot_git
# ---------------------------------------------------------------------------


class TestDownloadGitSourceRemoveDotGit:
    @patch("fromager.sources.gitutils.git_clone")
    def test_keeps_dot_git_by_default(
        self,
        mock_git_clone: MagicMock,
        tmp_path: pathlib.Path,
        tmp_context: context.WorkContext,
    ) -> None:
        dest = tmp_path / "source"
        dest.mkdir()
        dot_git = dest / ".git"
        dot_git.mkdir()
        (dot_git / "HEAD").write_text("ref: refs/heads/main\n")

        req = Requirement("test-pkg")
        sources.download_git_source(
            ctx=tmp_context,
            req=req,
            url_to_clone="https://github.test/org/repo.git",
            destination_dir=dest,
            ref="v1.0",
        )

        mock_git_clone.assert_called_once()
        assert dot_git.exists()

    @patch("fromager.sources.gitutils.git_clone")
    def test_removes_dot_git_when_enabled(
        self,
        mock_git_clone: MagicMock,
        tmp_path: pathlib.Path,
    ) -> None:
        ctx = _make_context_with_source(
            tmp_path,
            {"provider": "pypi-sdist"},
            git_options={"remove_dot_git": True},
        )
        dest = tmp_path / "source"
        dest.mkdir()
        dot_git = dest / ".git"
        dot_git.mkdir()
        (dot_git / "HEAD").write_text("ref: refs/heads/main\n")

        req = Requirement("test-pkg")
        sources.download_git_source(
            ctx=ctx,
            req=req,
            url_to_clone="https://github.test/org/repo.git",
            destination_dir=dest,
            ref="v1.0",
        )

        mock_git_clone.assert_called_once()
        assert not dot_git.exists()

    @patch("fromager.sources.gitutils.git_clone")
    def test_keeps_dot_git_when_disabled(
        self,
        mock_git_clone: MagicMock,
        tmp_path: pathlib.Path,
    ) -> None:
        ctx = _make_context_with_source(
            tmp_path,
            {"provider": "pypi-sdist"},
            git_options={"remove_dot_git": False},
        )
        dest = tmp_path / "source"
        dest.mkdir()
        dot_git = dest / ".git"
        dot_git.mkdir()
        (dot_git / "HEAD").write_text("ref: refs/heads/main\n")

        req = Requirement("test-pkg")
        sources.download_git_source(
            ctx=ctx,
            req=req,
            url_to_clone="https://github.test/org/repo.git",
            destination_dir=dest,
            ref="v1.0",
        )

        mock_git_clone.assert_called_once()
        assert dot_git.exists()


# ---------------------------------------------------------------------------
# GitOptions.remove_dot_git field
# ---------------------------------------------------------------------------


class TestGitOptionsRemoveDotGit:
    def test_default_is_false(self) -> None:
        opts = packagesettings.GitOptions()
        assert opts.remove_dot_git is False

    def test_can_set_true(self) -> None:
        opts = packagesettings.GitOptions(remove_dot_git=True)
        assert opts.remove_dot_git is True

    def test_can_set_false(self) -> None:
        opts = packagesettings.GitOptions(remove_dot_git=False)
        assert opts.remove_dot_git is False
