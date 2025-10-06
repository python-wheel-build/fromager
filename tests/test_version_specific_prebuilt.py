"""Test version-specific prebuilt settings functionality."""

import pathlib
import typing

from fromager.packagesettings import (
    PackageBuildInfo,
    PackageSettings,
    Settings,
    Variant,
)


class MockSettings:
    """Mock settings object for testing PackageBuildInfo."""

    def __init__(self, variant: str = "tpu-ubi9", max_jobs: int | None = None) -> None:
        self._variant = Variant(variant)
        self._patches_dir: pathlib.Path | None = None
        self._max_jobs = max_jobs

    @property
    def variant(self) -> Variant:
        return self._variant

    @property
    def patches_dir(self) -> pathlib.Path | None:
        return self._patches_dir

    @property
    def max_jobs(self) -> int | None:
        return self._max_jobs

    def variant_changelog(self) -> list[str]:
        return []


def test_version_specific_prebuilt_settings() -> None:
    """Test that version-specific prebuilt settings override variant defaults."""
    package_data = {
        "variants": {
            "tpu-ubi9": {
                "pre_built": False,
                "wheel_server_url": "https://default.example.com/simple/",
                "versions": {
                    "2.9.0.dev20250730": {
                        "pre_built": True,
                        "wheel_server_url": "https://prebuilt.example.com/simple/",
                    },
                    "0.24.0.dev20250730": {
                        "pre_built": True,
                    },
                    "2.8.0": {
                        "pre_built": False,
                    },
                },
            }
        }
    }

    ps = PackageSettings.from_mapping(
        package="test-package",
        parsed=package_data,
        source="test",
        has_config=True,
    )

    pbi = PackageBuildInfo(typing.cast(Settings, MockSettings()), ps)

    # Version with prebuilt and custom URL
    assert pbi.is_pre_built("2.9.0.dev20250730") is True
    assert (
        pbi.get_wheel_server_url("2.9.0.dev20250730")
        == "https://prebuilt.example.com/simple/"
    )

    # Version with prebuilt but no custom URL (uses variant default)
    assert pbi.is_pre_built("0.24.0.dev20250730") is True
    assert (
        pbi.get_wheel_server_url("0.24.0.dev20250730")
        == "https://default.example.com/simple/"
    )

    # Version explicitly set to build from source
    assert pbi.is_pre_built("2.8.0") is False
    assert pbi.get_wheel_server_url("2.8.0") == "https://default.example.com/simple/"

    # Unknown version uses variant default
    assert pbi.is_pre_built("1.0.0") is False
    assert pbi.get_wheel_server_url("1.0.0") == "https://default.example.com/simple/"

    # No version specified uses variant default
    assert pbi.is_pre_built() is False
    assert pbi.get_wheel_server_url() == "https://default.example.com/simple/"

    # Legacy property access
    assert pbi.pre_built is False
    assert pbi.wheel_server_url == "https://default.example.com/simple/"


def test_version_specific_env_vars() -> None:
    """Test that version-specific environment variables work correctly."""
    package_data = {
        "env": {
            "GLOBAL_VAR": "global_value",
        },
        "variants": {
            "cuda-ubi9": {
                "env": {
                    "VARIANT_VAR": "variant_value",
                    "OVERRIDE_ME": "variant_override",
                },
                "versions": {
                    "2.0.0": {
                        "env": {
                            "VERSION_VAR": "version_value",
                            "OVERRIDE_ME": "version_override",
                        }
                    }
                },
            }
        },
    }

    ps = PackageSettings.from_mapping(
        package="test-package",
        parsed=package_data,
        source="test",
        has_config=True,
    )

    pbi = PackageBuildInfo(
        typing.cast(Settings, MockSettings(variant="cuda-ubi9", max_jobs=1)), ps
    )

    # With version: should include all levels with version taking precedence
    env_with_version = pbi.get_extra_environ(
        template_env={}, build_env=None, version="2.0.0"
    )
    assert env_with_version["GLOBAL_VAR"] == "global_value"
    assert env_with_version["VARIANT_VAR"] == "variant_value"
    assert env_with_version["VERSION_VAR"] == "version_value"
    assert env_with_version["OVERRIDE_ME"] == "version_override"

    # Without version: should not include version-specific vars
    env_without_version = pbi.get_extra_environ(
        template_env={},
        build_env=None,
    )
    assert env_without_version["GLOBAL_VAR"] == "global_value"
    assert env_without_version["VARIANT_VAR"] == "variant_value"
    assert "VERSION_VAR" not in env_without_version
    assert env_without_version["OVERRIDE_ME"] == "variant_override"


def test_backward_compatibility() -> None:
    """Test that existing configurations without version-specific settings still work."""
    package_data = {
        "variants": {
            "cpu-ubi9": {
                "pre_built": True,
                "wheel_server_url": "https://legacy.example.com/simple/",
            }
        }
    }

    ps = PackageSettings.from_mapping(
        package="legacy-package",
        parsed=package_data,
        source="test",
        has_config=True,
    )

    pbi = PackageBuildInfo(typing.cast(Settings, MockSettings(variant="cpu-ubi9")), ps)

    # All methods should return the variant-wide setting
    assert pbi.pre_built is True
    assert pbi.is_pre_built() is True
    assert pbi.is_pre_built("1.0.0") is True

    assert pbi.wheel_server_url == "https://legacy.example.com/simple/"
    assert pbi.get_wheel_server_url() == "https://legacy.example.com/simple/"
    assert pbi.get_wheel_server_url("1.0.0") == "https://legacy.example.com/simple/"
