import pathlib
import typing
from unittest.mock import Mock, patch

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import context, packagesettings, resolver, sources
from fromager.packagesettings import CreateFile
from fromager.requirements_file import SourceType


@patch("fromager.sources.download_url")
def test_invalid_tarfile(mock_download_url: typing.Any, tmp_path: pathlib.Path) -> None:
    mock_download_url.return_value = pathlib.Path(tmp_path / "test" / "fake_wheel.txt")
    fake_url = "https://www.thisisafakeurl.com"
    fake_dir = tmp_path / "test"
    fake_dir.mkdir()
    text_file = fake_dir / "fake_wheel.txt"
    text_file.write_text("This is a test file")
    req = Requirement("test_pkg==42.1.2")
    with pytest.raises(ValueError):
        sources._download_source_check(req=req, destination_dir=fake_dir, url=fake_url)


@patch("fromager.resolver.resolve")
@patch("fromager.sources._download_source_check")
def test_default_download_source_from_settings(
    download_source_check: Mock,
    resolve: Mock,
    testdata_context: context.WorkContext,
) -> None:
    resolve.return_value = ("url", Version("42.1.2"))
    download_source_check.return_value = pathlib.Path("filename.zip")
    req = Requirement("test_pkg==42.1.2")
    sdist_server_url = "https://sdist.test/egg"

    sources.default_resolve_source(testdata_context, req, sdist_server_url)

    resolve.assert_called_with(
        ctx=testdata_context,
        req=req,
        sdist_server_url=sdist_server_url,
        include_sdists=True,
        include_wheels=True,
        req_type=None,
        ignore_platform=True,
    )

    sources.default_download_source(
        testdata_context,
        req,
        Version("42.1.2"),
        "url",
        testdata_context.sdists_downloads,
    )

    download_source_check.assert_called_with(
        req=req,
        destination_dir=testdata_context.sdists_downloads,
        url="https://egg.test/test-pkg/v42.1.2.tar.gz",
        destination_filename="test-pkg-42.1.2.tar.gz",
    )


@patch("fromager.resolver.resolve")
@patch("fromager.sources._download_source_check")
@patch.multiple(
    packagesettings.PackageBuildInfo,
    resolver_include_sdists=False,
    resolver_include_wheels=True,
    resolver_sdist_server_url=Mock(return_value="url"),
)
def test_default_download_source_with_predefined_resolve_dist(
    download_source_check: Mock,
    resolve: Mock,
    tmp_context: context.WorkContext,
) -> None:
    resolve.return_value = ("url", Version("1.0"))
    download_source_check.return_value = pathlib.Path("filename")
    req = Requirement("foo==1.0")

    sources.default_resolve_source(tmp_context, req, resolver.PYPI_SERVER_URL)

    resolve.assert_called_with(
        ctx=tmp_context,
        req=req,
        sdist_server_url="url",
        include_sdists=False,
        include_wheels=True,
        req_type=None,
        ignore_platform=False,
    )


@patch("fromager.sources.default_resolve_source")
def test_invalid_version(
    mock_default_resolve_source: typing.Any, tmp_context: context.WorkContext
) -> None:
    req = Requirement("fake==1.0")
    sdist_server_url = resolver.PYPI_SERVER_URL
    mock_default_resolve_source.return_value = (
        "fakesdisturl.com",
        "fake version 1.0",
    )
    mock_default_resolve_source.__name__ = "mock_default_resolve_source"
    with pytest.raises(ValueError):
        sources.resolve_source(
            ctx=tmp_context,
            req=req,
            sdist_server_url=sdist_server_url,
        )


@patch("logging.Logger.warning")
@patch("fromager.sources._apply_patch")
def test_patch_sources_apply_unversioned_and_versioned(
    apply_patch: Mock,
    warning: Mock,
    tmp_path: pathlib.Path,
    testdata_context: context.WorkContext,
) -> None:
    source_root_dir = tmp_path / "test_pkg-1.0.2"
    source_root_dir.mkdir()

    sources.patch_source(
        ctx=testdata_context,
        source_root_dir=source_root_dir,
        req=Requirement("test-pkg==1.0.2"),
        version=Version("1.0.2"),
    )
    assert apply_patch.call_count == 5
    warning.assert_not_called()

    apply_patch.reset_mock()
    source_root_dir = tmp_path / "test_pkg-1.0.1"
    source_root_dir.mkdir()

    sources.patch_source(
        ctx=testdata_context,
        source_root_dir=source_root_dir,
        req=Requirement("test-pkg==1.0.1"),
        version=Version("1.0.1"),
    )
    assert apply_patch.call_count == 2
    warning.assert_not_called()

    apply_patch.reset_mock()
    source_root_dir = tmp_path / "test_other_pkg-1.0.1"
    source_root_dir.mkdir()

    sources.patch_source(
        ctx=testdata_context,
        source_root_dir=source_root_dir,
        req=Requirement("test-other-pkg==1.0.1"),
        version=Version("1.0.1"),
    )
    assert apply_patch.call_count == 0
    warning.assert_called_once()


@patch("fromager.sources._apply_patch")
def test_patch_sources_apply_only_unversioned(
    apply_patch: Mock,
    tmp_path: pathlib.Path,
    tmp_context: context.WorkContext,
) -> None:
    patches_dir = tmp_path / "patches_dir"
    patches_dir.mkdir()
    tmp_context.settings.patches_dir = patches_dir

    deepspeed_version_patch = patches_dir / "deepspeed-0.5.0"
    deepspeed_version_patch.mkdir()
    version_patch_file = deepspeed_version_patch / "deepspeed-0.5.0.patch"
    version_patch_file.write_text("This is a test patch")

    deepspeed_unversioned_patch = patches_dir / "deepspeed"
    deepspeed_unversioned_patch.mkdir()
    unversioned_patch_file = deepspeed_unversioned_patch / "deepspeed-update.patch"
    unversioned_patch_file.write_text("This is a test patch")

    source_root_dir = tmp_path / "deepspeed-0.5.0"
    source_root_dir.mkdir()

    req = Requirement("deepspeed")

    sources.patch_source(
        ctx=tmp_context,
        source_root_dir=source_root_dir,
        req=req,
        version=Version("0.6.0"),
    )
    apply_patch.assert_called_once_with(req, unversioned_patch_file, source_root_dir)


@pytest.mark.parametrize(
    "dist_name,version_string,sdist_filename,okay",
    [
        ("mypkg", "1.2", "mypkg-1.2.tar.gz", True),
        ("mypkg", "1.2", "unknown-1.2.tar.gz", False),
        ("mypkg", "1.2", "mypkg-1.2.1.tar.gz", False),
        ("oslo.messaging", "14.7.0", "oslo.messaging-14.7.0.tar.gz", True),
        ("cython", "3.0.10", "Cython-3.0.10.tar.gz", True),
        # parse_sdist_filename() accepts a dash in the name
        ("fromage_test", "9.9.9", "fromage-test-9.9.9.tar.gz", True),
        ("fromage-test", "9.9.9", "fromage-test-9.9.9.tar.gz", True),
        ("fromage_test", "9.9.9", "fromage_test-9.9.9.tar.gz", True),
        ("ruamel-yaml", "0.18.6", "ruamel.yaml-0.18.6.tar.gz", True),
    ],
)
def test_validate_sdist_file(
    dist_name: str, version_string: str, sdist_filename: pathlib.Path, okay: bool
) -> None:
    req = Requirement(dist_name)
    version = Version(version_string)
    sdist_file = pathlib.Path(sdist_filename)
    if okay:
        sources.validate_sdist_filename(req, version, sdist_file)
    else:
        with pytest.raises(ValueError):
            sources.validate_sdist_filename(req, version, sdist_file)


@patch("fromager.resolver.resolve_from_provider")
@patch("fromager.resolver.GitHubTagProvider")
def test_resolve_with_configured_github_provider(
    mock_github_cls: Mock,
    mock_resolve_from_provider: Mock,
    tmp_context: context.WorkContext,
) -> None:
    """Verify _resolve_with_configured_provider creates GitHubTagProvider."""
    mock_provider = Mock()
    mock_github_cls.return_value = mock_provider
    mock_resolve_from_provider.return_value = (
        "https://github.com/org/repo/archive/v1.0.tar.gz",
        Version("1.0"),
    )

    ps = packagesettings.PackageSettings.from_string(
        "github-pkg",
        """
resolver_dist:
  provider: github
  organization: myorg
  repo: myrepo
  tag_matcher: "v(.*)"
""",
    )
    settings = packagesettings.Settings(
        settings=packagesettings.SettingsFile(),
        package_settings=[ps],
        variant="cpu",
        patches_dir=tmp_context.settings.patches_dir,
        max_jobs=1,
    )
    tmp_context.settings = settings

    req = Requirement("github-pkg==1.0")
    pbi = tmp_context.package_build_info(req)
    url, version = sources._resolve_with_configured_provider(
        ctx=tmp_context,
        req=req,
        pbi=pbi,
    )
    assert url == "https://github.com/org/repo/archive/v1.0.tar.gz"
    assert version == Version("1.0")
    mock_github_cls.assert_called_once()
    mock_resolve_from_provider.assert_called_once_with(mock_provider, req)


@patch("fromager.resolver.resolve_from_provider")
@patch("fromager.resolver.GitLabTagProvider")
def test_resolve_with_configured_gitlab_provider(
    mock_gitlab_cls: Mock,
    mock_resolve_from_provider: Mock,
    tmp_context: context.WorkContext,
) -> None:
    """Verify _resolve_with_configured_provider creates GitLabTagProvider."""
    mock_provider = Mock()
    mock_gitlab_cls.return_value = mock_provider
    mock_resolve_from_provider.return_value = (
        "https://gitlab.com/group/project/-/archive/v1.0/project-v1.0.tar.gz",
        Version("1.0"),
    )

    ps = packagesettings.PackageSettings.from_string(
        "gitlab-pkg",
        """
resolver_dist:
  provider: gitlab
  project_path: group/project
  server_url: https://gitlab.example.com
""",
    )
    settings = packagesettings.Settings(
        settings=packagesettings.SettingsFile(),
        package_settings=[ps],
        variant="cpu",
        patches_dir=tmp_context.settings.patches_dir,
        max_jobs=1,
    )
    tmp_context.settings = settings

    req = Requirement("gitlab-pkg==1.0")
    pbi = tmp_context.package_build_info(req)
    _url, _version = sources._resolve_with_configured_provider(
        ctx=tmp_context,
        req=req,
        pbi=pbi,
    )
    mock_gitlab_cls.assert_called_once_with(
        project_path="group/project",
        server_url="https://gitlab.example.com",
        constraints=tmp_context.constraints,
        matcher=None,
    )
    mock_resolve_from_provider.assert_called_once_with(mock_provider, req)


@patch("fromager.resolver.resolve_from_provider")
@patch("fromager.resolver.GitLabTagProvider")
def test_resolve_gitlab_with_org_repo_fallback(
    mock_gitlab_cls: Mock,
    mock_resolve_from_provider: Mock,
    tmp_context: context.WorkContext,
) -> None:
    """Verify GitLab provider uses org/repo when project_path is not set."""
    mock_provider = Mock()
    mock_gitlab_cls.return_value = mock_provider
    mock_resolve_from_provider.return_value = (
        "https://gitlab.com/myorg/myrepo/-/archive/v1.0.tar.gz",
        Version("1.0"),
    )

    ps = packagesettings.PackageSettings.from_string(
        "gitlab-org-pkg",
        """
resolver_dist:
  provider: gitlab
  organization: myorg
  repo: myrepo
""",
    )
    settings = packagesettings.Settings(
        settings=packagesettings.SettingsFile(),
        package_settings=[ps],
        variant="cpu",
        patches_dir=tmp_context.settings.patches_dir,
        max_jobs=1,
    )
    tmp_context.settings = settings

    req = Requirement("gitlab-org-pkg==1.0")
    pbi = tmp_context.package_build_info(req)
    sources._resolve_with_configured_provider(
        ctx=tmp_context,
        req=req,
        pbi=pbi,
    )
    mock_gitlab_cls.assert_called_once_with(
        project_path="myorg/myrepo",
        server_url="https://gitlab.com",
        constraints=tmp_context.constraints,
        matcher=None,
    )


@patch("fromager.resolver.resolve")
def test_default_resolve_source_with_yaml_provider(
    mock_resolve: Mock,
    tmp_context: context.WorkContext,
) -> None:
    """Verify default_resolve_source skips PyPI when provider is configured."""
    ps = packagesettings.PackageSettings.from_string(
        "provider-pkg",
        """
resolver_dist:
  provider: github
  organization: myorg
  repo: myrepo
""",
    )
    settings = packagesettings.Settings(
        settings=packagesettings.SettingsFile(),
        package_settings=[ps],
        variant="cpu",
        patches_dir=tmp_context.settings.patches_dir,
        max_jobs=1,
    )
    tmp_context.settings = settings

    req = Requirement("provider-pkg==1.0")

    with patch.object(
        sources,
        "_resolve_with_configured_provider",
        return_value=("https://example.com/archive.tar.gz", Version("1.0")),
    ) as mock_configured:
        url, version = sources.default_resolve_source(
            tmp_context, req, resolver.PYPI_SERVER_URL
        )

    mock_configured.assert_called_once()
    mock_resolve.assert_not_called()
    assert url == "https://example.com/archive.tar.gz"
    assert version == Version("1.0")


def test_get_source_type_with_yaml_provider(
    tmp_context: context.WorkContext,
) -> None:
    """Verify get_source_type detects YAML-configured provider."""
    ps = packagesettings.PackageSettings.from_string(
        "source-type-pkg",
        """
resolver_dist:
  provider: github
  organization: myorg
  repo: myrepo
""",
    )
    settings = packagesettings.Settings(
        settings=packagesettings.SettingsFile(),
        package_settings=[ps],
        variant="cpu",
        patches_dir=tmp_context.settings.patches_dir,
        max_jobs=1,
    )
    tmp_context.settings = settings

    req = Requirement("source-type-pkg==1.0")
    source_type = sources.get_source_type(tmp_context, req)
    assert source_type == SourceType.OVERRIDE


@patch("fromager.vendor_rust.vendor_rust")
@patch("fromager.pyproject.apply_project_override")
@patch("fromager.sources.patch_source")
@patch("fromager.sources.ensure_pkg_info")
def test_prepare_new_source_calls_ensure_pkg_info(
    ensure_pkg_info: Mock,
    patch_source: Mock,
    apply_project_override: Mock,
    vendor_rust: Mock,
    tmp_path: pathlib.Path,
    tmp_context: context.WorkContext,
) -> None:
    """Verify prepare_new_source calls ensure_pkg_info before patching."""
    req = Requirement("foo==1.0")
    source_root_dir = tmp_path / "foo-1.0"
    source_root_dir.mkdir()
    version = Version("1.0")

    sources.prepare_new_source(tmp_context, req, source_root_dir, version)

    ensure_pkg_info.assert_called_once()
    patch_source.assert_called_once()
    apply_project_override.assert_called_once()
    vendor_rust.assert_called_once()


@patch("fromager.vendor_rust.vendor_rust")
@patch("fromager.pyproject.apply_project_override")
@patch("fromager.sources.patch_source")
@patch("fromager.sources.ensure_pkg_info")
def test_prepare_new_source_vendor_rust_default_after_patch(
    ensure_pkg_info: Mock,
    patch_source: Mock,
    apply_project_override: Mock,
    vendor_rust: Mock,
    tmp_path: pathlib.Path,
    tmp_context: context.WorkContext,
) -> None:
    """Verify vendor_rust runs after patch_source by default."""
    call_order: list[str] = []
    patch_source.side_effect = lambda *a, **kw: call_order.append("patch")
    vendor_rust.side_effect = lambda *a, **kw: call_order.append("vendor_rust")

    req = Requirement("foo==1.0")
    source_root_dir = tmp_path / "foo-1.0"
    source_root_dir.mkdir()

    sources.prepare_new_source(tmp_context, req, source_root_dir, Version("1.0"))

    assert call_order == ["patch", "vendor_rust"]


@patch("fromager.vendor_rust.vendor_rust")
@patch("fromager.pyproject.apply_project_override")
@patch("fromager.sources.patch_source")
@patch("fromager.sources.ensure_pkg_info")
@patch.object(
    packagesettings.PackageBuildInfo,
    "vendor_rust_before_patch",
    new_callable=lambda: property(lambda self: True),
)
def test_prepare_new_source_vendor_rust_before_patch(
    _vendor_rust_prop: Mock,
    ensure_pkg_info: Mock,
    patch_source: Mock,
    apply_project_override: Mock,
    vendor_rust: Mock,
    tmp_path: pathlib.Path,
    tmp_context: context.WorkContext,
) -> None:
    """Verify vendor_rust runs before patch_source when setting is True."""
    call_order: list[str] = []
    patch_source.side_effect = lambda *a, **kw: call_order.append("patch")
    vendor_rust.side_effect = lambda *a, **kw: call_order.append("vendor_rust")

    req = Requirement("foo==1.0")
    source_root_dir = tmp_path / "foo-1.0"
    source_root_dir.mkdir()

    sources.prepare_new_source(tmp_context, req, source_root_dir, Version("1.0"))

    assert call_order == ["vendor_rust", "patch"]


@patch("fromager.vendor_rust.vendor_rust")
@patch("fromager.pyproject.apply_project_override")
@patch("fromager.sources.patch_source")
@patch("fromager.sources.ensure_pkg_info")
@patch.object(
    packagesettings.PackageBuildInfo,
    "create_files",
    new_callable=lambda: property(
        lambda self: [
            CreateFile(path="src/pkg/__init__.py", content=""),
            CreateFile(
                path="src/pkg/version.py",
                content='__version__ = "${version}"',
            ),
        ]
    ),
)
def test_prepare_new_source_create_files(
    _create_files_prop: Mock,
    ensure_pkg_info: Mock,
    patch_source: Mock,
    apply_project_override: Mock,
    vendor_rust: Mock,
    tmp_path: pathlib.Path,
    tmp_context: context.WorkContext,
) -> None:
    """Verify create_source_files creates files with template substitution."""
    req = Requirement("foo==1.0")
    source_root_dir = tmp_path / "foo-1.0"
    source_root_dir.mkdir()

    sources.prepare_new_source(tmp_context, req, source_root_dir, Version("1.0"))

    init_file = source_root_dir / "src" / "pkg" / "__init__.py"
    assert init_file.exists()
    assert init_file.read_text() == ""

    version_file = source_root_dir / "src" / "pkg" / "version.py"
    assert version_file.exists()
    assert version_file.read_text() == '__version__ = "1.0"'


def test_create_source_files_no_files(
    tmp_path: pathlib.Path,
    tmp_context: context.WorkContext,
) -> None:
    """Verify create_source_files is a no-op when no files are configured."""
    req = Requirement("foo==1.0")
    source_root_dir = tmp_path / "foo-1.0"
    source_root_dir.mkdir()

    sources.create_source_files(tmp_context, req, source_root_dir, Version("1.0"))

    assert list(source_root_dir.iterdir()) == []


@patch.object(
    packagesettings.PackageBuildInfo,
    "create_files",
    new_callable=lambda: property(
        lambda self: [
            CreateFile(path="nested/dir/file.txt", content="hello"),
        ]
    ),
)
def test_create_source_files_creates_parent_dirs(
    _create_files_prop: Mock,
    tmp_path: pathlib.Path,
    tmp_context: context.WorkContext,
) -> None:
    """Verify create_source_files creates parent directories."""
    req = Requirement("foo==1.0")
    source_root_dir = tmp_path / "foo-1.0"
    source_root_dir.mkdir()

    sources.create_source_files(tmp_context, req, source_root_dir, Version("1.0"))

    created_file = source_root_dir / "nested" / "dir" / "file.txt"
    assert created_file.exists()
    assert created_file.read_text() == "hello"


@patch.object(
    packagesettings.PackageBuildInfo,
    "create_files",
    new_callable=lambda: property(
        lambda self: [
            CreateFile(path="existing.txt", content="new content"),
        ]
    ),
)
def test_create_source_files_overwrites_existing(
    _create_files_prop: Mock,
    tmp_path: pathlib.Path,
    tmp_context: context.WorkContext,
) -> None:
    """Verify create_source_files overwrites existing files."""
    req = Requirement("foo==1.0")
    source_root_dir = tmp_path / "foo-1.0"
    source_root_dir.mkdir()
    existing = source_root_dir / "existing.txt"
    existing.write_text("old content")

    sources.create_source_files(tmp_context, req, source_root_dir, Version("1.0"))

    assert existing.read_text() == "new content"
