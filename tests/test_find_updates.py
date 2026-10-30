"""Tests for constraint parsing and update resolution."""

import datetime
import pathlib
from unittest.mock import patch

import pytest
import requests_mock
from click.testing import CliRunner
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import context, packagesettings, resolver
from fromager.candidate import Candidate, Cooldown
from fromager.commands.find_updates import (
    _find_newer_versions,
    _get_constraint_version,
    find_updates,
)


@pytest.mark.parametrize(
    ("config", "distribution_type", "index_url", "expected_versions"),
    [
        (
            "source:\n  provider: pypi-sdist\n  index_url: https://source.test/simple/\n",
            "default",
            "https://source.test/simple/",
            ["2.0.0"],
        ),
        (
            "source:\n  provider: pypi-prebuilt\n  index_url: https://source.test/simple/\n",
            "default",
            "https://source.test/simple/",
            ["3.0.0"],
        ),
        (
            "source:\n  provider: pypi-sdist\n  index_url: https://source.test/simple/\n",
            "wheel",
            "https://source.test/simple/",
            ["2.0.0"],
        ),
        (
            "source:\n  provider: pypi-prebuilt\n  index_url: https://source.test/simple/\n",
            "sdist",
            "https://source.test/simple/",
            ["3.0.0"],
        ),
        (
            "source:\n  provider: pypi-sdist\n"
            "variants:\n  cpu:\n    source:\n      provider: pypi-prebuilt\n"
            "      index_url: https://source.test/simple/\n",
            "default",
            "https://source.test/simple/",
            ["3.0.0"],
        ),
        ("", "default", "https://caller.test/simple/", ["2.0.0"]),
        *[
            (
                "resolver_dist:\n  sdist_server_url: https://legacy.test/simple/\n"
                "  include_sdists: false\n  include_wheels: true\n",
                distribution_type,
                "https://legacy.test/simple/",
                expected_versions,
            )
            for distribution_type, expected_versions in [
                ("default", ["3.0.0"]),
                ("sdist", ["2.0.0"]),
                ("wheel", ["3.0.0"]),
                ("both", ["2.0.0", "3.0.0"]),
            ]
        ],
    ],
    ids=[
        "source-sdist",
        "source-prebuilt",
        "source-sdist-overrides-distribution-option",
        "source-prebuilt-overrides-distribution-option",
        "source-variant",
        "legacy-caller-index",
        "legacy-default",
        "legacy-sdist",
        "legacy-wheel",
        "legacy-both",
    ],
)
def test_find_updates_resolves_configured_package(
    config: str,
    distribution_type: str,
    index_url: str,
    expected_versions: list[str],
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
    cli_runner: CliRunner,
    requests_mock: requests_mock.Mocker,
) -> None:
    """Resolve updates using source profiles or legacy distribution settings."""
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "test-pkg.yaml").write_text(config)
    tmp_context.settings = packagesettings.Settings.from_files(
        settings_file=tmp_path / "settings.yaml",
        settings_dir=settings_dir,
        patches_dir=tmp_path / "patches",
        variant="cpu",
        max_jobs=None,
    )
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text("test-pkg==1.0.0\n")
    resolver.BaseProvider.clear_cache()
    requests_mock.get(
        f"{index_url}test-pkg/",
        text=(
            '<a href="test_pkg-1.0.0.tar.gz">test_pkg-1.0.0.tar.gz</a>'
            '<a href="test_pkg-2.0.0.tar.gz">test_pkg-2.0.0.tar.gz</a>'
            '<a href="test_pkg-3.0.0-py3-none-any.whl">test_pkg-3.0.0-py3-none-any.whl</a>'
        ),
    )

    result = cli_runner.invoke(
        find_updates,
        [
            "--sdist-server-url",
            "https://caller.test/simple/",
            "--distribution-type",
            distribution_type,
            str(constraints_file),
        ],
        obj=tmp_context,
    )

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        f"test-pkg=={version}" for version in expected_versions
    ]
    assert requests_mock.call_count == 1


@pytest.mark.parametrize("source_provider", [None, "pypi-sdist", "pypi-prebuilt"])
@pytest.mark.parametrize(
    ("global_days", "package_days"),
    [(7, None), (None, 7)],
    ids=["global-cooldown", "package-cooldown"],
)
@pytest.mark.parametrize(
    "include_old_release", [True, False], ids=["mixed", "all-recent"]
)
def test_find_updates_ignores_release_age_cooldown(
    source_provider: str | None,
    global_days: int | None,
    package_days: int | None,
    include_old_release: bool,
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
    cli_runner: CliRunner,
    requests_mock: requests_mock.Mocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Report recent updates with either source or legacy configuration."""
    profile: dict[str, str | int] = {}
    if source_provider is not None:
        profile["provider"] = source_provider
    if package_days is not None:
        profile["min_release_age"] = package_days
    package_settings = packagesettings.PackageSettings.from_mapping(
        "test-pkg",
        {"source" if source_provider is not None else "resolver_dist": profile},
        source="test",
        has_config=True,
    )
    tmp_context.settings = packagesettings.Settings(
        settings=packagesettings.SettingsFile(),
        package_settings=[package_settings],
        patches_dir=tmp_path / "patches",
        variant="cpu",
        max_jobs=None,
    )
    now = datetime.datetime.now(datetime.UTC)
    if global_days is not None:
        tmp_context.cooldown = Cooldown(
            min_age=datetime.timedelta(days=global_days),
            bootstrap_time=now,
        )
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text("test-pkg==1.0.0\n")
    suffix = "-py3-none-any.whl" if source_provider == "pypi-prebuilt" else ".tar.gz"
    releases = [("2.0.0", 1)]
    if include_old_release:
        releases.append(("1.0.0", 30))
    resolver.BaseProvider.clear_cache()
    requests_mock.get(
        "https://pypi.org/simple/test-pkg/",
        headers={"Content-Type": "application/vnd.pypi.simple.v1+json"},
        json={
            "meta": {"api-version": "1.1"},
            "name": "test-pkg",
            "files": [
                {
                    "filename": f"test_pkg-{version}{suffix}",
                    "url": f"https://files.test/test_pkg-{version}{suffix}",
                    "hashes": {},
                    "upload-time": (now - datetime.timedelta(days=days)).isoformat(),
                }
                for version, days in releases
            ],
        },
    )

    result = cli_runner.invoke(find_updates, [str(constraints_file)], obj=tmp_context)

    assert result.exit_code == 0, result.output
    assert result.output == "test-pkg==2.0.0\n"
    assert "Could not check versions" not in caplog.text
    assert "cooldown blocked" not in caplog.text


def test_find_newer_versions_preserves_legacy_provider_hook(
    tmp_context: context.WorkContext,
) -> None:
    """Continue resolving legacy packages through their provider override."""
    candidate = Candidate(
        name="test-pkg",
        version=Version("2.0.0"),
        url="https://hook.test/test_pkg-2.0.0.tar.gz",
    )
    provider = resolver.GenericProvider(
        version_source=lambda identifier: [candidate],
        use_resolver_cache=False,
    )
    with patch(
        "fromager.overrides.find_override_method",
        return_value=lambda **kwargs: provider,
    ):
        versions = _find_newer_versions(
            tmp_context,
            Requirement("test-pkg==1.0.0"),
            Version("1.0.0"),
            "default",
            "https://caller.test/simple/",
        )

    assert versions == [Version("2.0.0")]


class TestGetConstraintVersion:
    """Test cases for _get_constraint_version function."""

    def test_equality_constraint(self) -> None:
        """Test that equality constraints return the correct version."""
        req = Requirement("package==1.2.3")
        result = _get_constraint_version(req)
        assert result == Version("1.2.3")

    def test_less_than_constraint(self) -> None:
        """Test that less than constraints return the correct version."""
        req = Requirement("package<2.0.0")
        result = _get_constraint_version(req)
        assert result == Version("2.0.0")

    def test_less_than_or_equal_constraint(self) -> None:
        """Test that less than or equal constraints return the correct version."""
        req = Requirement("package<=1.5.0")
        result = _get_constraint_version(req)
        assert result == Version("1.5.0")

    def test_greater_than_constraint_unsupported(self) -> None:
        """Test that greater than constraints return None (unsupported)."""
        req = Requirement("package>1.0.0")
        result = _get_constraint_version(req)
        assert result is None

    def test_greater_than_or_equal_constraint_unsupported(self) -> None:
        """Test that greater than or equal constraints return None (unsupported)."""
        req = Requirement("package>=1.0.0")
        result = _get_constraint_version(req)
        assert result is None

    def test_no_version_constraint(self) -> None:
        """Test that requirements without version constraints return None."""
        req = Requirement("package")
        result = _get_constraint_version(req)
        assert result is None

    def test_multiple_constraints_with_one_supported(self) -> None:
        """Test that multiple constraints with one supported constraint return the supported one."""
        req = Requirement("package>=1.0.0,<2.0.0")
        result = _get_constraint_version(req)
        assert result == Version("2.0.0")

    def test_constraint_with_markers(self) -> None:
        """Test that constraints with environment markers still work correctly."""
        req = Requirement("package==1.2.3; python_version >= '3.8'")
        result = _get_constraint_version(req)
        assert result == Version("1.2.3")

    def test_tilde_equal_constraint_supported(self) -> None:
        """Test that tilde equal constraints (~=) return the correct version."""
        req = Requirement("package~=1.4.2")
        result = _get_constraint_version(req)
        assert result == Version("1.4.2")

    def test_not_equal_constraint_supported(self) -> None:
        """Test that not equal constraints (!=) return the correct version."""
        req = Requirement("package!=1.0.0")
        result = _get_constraint_version(req)
        assert result == Version("1.0.0")

    def test_arbitrary_equality_constraint_supported(self) -> None:
        """Test that arbitrary equality constraints (===) return the correct version."""
        req = Requirement("package===1.0.0")
        result = _get_constraint_version(req)
        assert result == Version("1.0.0")

    def test_invalid_version_format(self) -> None:
        """Test that invalid version formats return None."""
        # We need to test the case where Version() construction fails
        # Let's create a requirement and then mock the Version parsing
        req = Requirement("package==1.0.0")

        with patch("fromager.commands.find_updates.Version") as mock_version:
            mock_version.side_effect = ValueError("Invalid version")
            result = _get_constraint_version(req)
            assert result is None
