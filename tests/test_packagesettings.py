import pathlib

import pydantic
import pytest
from packaging.utils import NormalizedName
from packaging.version import Version

from fromager.packagesettings import (
    BuildDirectory,
    EnvVars,
    Package,
    PackageSettings,
    Settings,
    SettingsFile,
    Variant,
)

TEST_PKG = "test-pkg"
TEST_EMPTY_PKG = "test-empty-pkg"
TEST_OTHER_PKG = "test-other-pkg"

FULL_EXPECTED = {
    "build_dir": pathlib.Path("python"),
    "changelog": {
        Version("1.0.1"): ["fixed bug"],
        Version("1.0.2"): ["more bugs", "rebuild"],
    },
    "download_source": {
        "destination_filename": "${canonicalized_name}-${version}.tar.gz",
        "url": "https://egg.test/${canonicalized_name}/v${version}.tar.gz",
    },
    "env": {
        "EGG": "spam",
        "EGG_AGAIN": "$EGG",
        "SPAM": "alot $EXTRA",
        "QUOTES": "A\"BC'$$EGG",
    },
    "name": "test-pkg",
    "has_config": True,
    "resolver_dist": {
        "include_sdists": True,
        "include_wheels": False,
        "sdist_server_url": "https://sdist.test/egg",
    },
    "variants": {
        "cpu": {
            "env": {"EGG": "spam ${EGG}", "EGG_AGAIN": "$EGG"},
            "wheel_server_url": "https://wheel.test/simple",
            "pre_built": False,
        },
        "rocm": {
            "env": {"SPAM": ""},
            "wheel_server_url": None,
            "pre_built": True,
        },
        "cuda": {
            "env": {},
            "wheel_server_url": None,
            "pre_built": False,
        },
    },
}

EMPTY_EXPECTED = {
    "name": "test-empty-pkg",
    "build_dir": None,
    "changelog": {},
    "env": {},
    "download_source": {
        "url": None,
        "destination_filename": None,
    },
    "has_config": True,
    "resolver_dist": {
        "sdist_server_url": None,
        "include_sdists": True,
        "include_wheels": False,
    },
    "variants": {},
}


@pytest.fixture
def test_settings(testdata_path, tmp_path) -> Settings:
    overrides = testdata_path / "context" / "overrides"
    return Settings.from_files(
        settings_file=overrides / "settings.yaml",
        settings_dir=overrides / "settings",
        variant=Variant("cpu"),
        patches_dir=overrides / "patches",
    )


def test_parse_full(testdata_path: pathlib.Path) -> None:
    filename = testdata_path / "context/overrides/settings/test_pkg.yaml"
    p = PackageSettings.from_string(TEST_PKG, filename.read_text())
    assert p.model_dump() == FULL_EXPECTED


def test_parse_full_file(testdata_path: pathlib.Path) -> None:
    filename = testdata_path / "context/overrides/settings/test_pkg.yaml"
    p = PackageSettings.from_file(filename)
    assert p.model_dump() == FULL_EXPECTED


def test_parse_minimal(testdata_path) -> None:
    filename = testdata_path / "context/overrides/settings/test_empty_pkg.yaml"
    p = PackageSettings.from_string(TEST_EMPTY_PKG, filename.read_text())
    assert p.model_dump() == EMPTY_EXPECTED


def test_parse_minimal_file(testdata_path: pathlib.Path) -> None:
    filename = testdata_path / "context/overrides/settings/test_empty_pkg.yaml"
    p = PackageSettings.from_file(filename)
    assert p.model_dump() == EMPTY_EXPECTED


def test_default_settings() -> None:
    p = PackageSettings.from_default(TEST_EMPTY_PKG)
    expected = EMPTY_EXPECTED.copy()
    expected["has_config"] = False
    assert p.model_dump() == expected


def test_pbi_test_pkg_extra_environ(test_settings: Settings) -> None:
    pbi = test_settings.package_build_info(TEST_PKG)
    assert pbi.get_extra_environ(template_env={"EXTRA": "extra"}) == {
        "EGG": "spam spam",
        "EGG_AGAIN": "spam spam",
        "QUOTES": "A\"BC'$EGG",  # $$EGG is transformed into $EGG
        "SPAM": "alot extra",
    }

    test_settings.variant = Variant("rocm")
    pbi = test_settings.package_build_info(TEST_PKG)
    assert pbi.get_extra_environ(template_env={"EXTRA": "extra"}) == {
        "EGG": "spam",
        "EGG_AGAIN": "spam",
        "QUOTES": "A\"BC'$EGG",
        "SPAM": "",
    }

    test_settings.variant = Variant("cuda")
    pbi = test_settings.package_build_info(TEST_PKG)
    assert pbi.get_extra_environ(template_env={"EXTRA": "spam"}) == {
        "EGG": "spam",
        "EGG_AGAIN": "spam",
        "QUOTES": "A\"BC'$EGG",
        "SPAM": "alot spam",
    }


def test_pbi_test_pkg(test_settings: Settings) -> None:
    pbi = test_settings.package_build_info(TEST_PKG)
    assert pbi.package == NormalizedName(TEST_PKG)
    assert pbi.variant == Variant(test_settings.variant)
    assert pbi.pre_built is False
    assert pbi.has_config is True
    assert pbi.wheel_server_url == "https://wheel.test/simple"
    assert pbi.override_module_name == "test_pkg"
    assert (
        pbi.download_source_url(Version("1.0.2"), resolve_template=False)
        == "https://egg.test/${canonicalized_name}/v${version}.tar.gz"
    )
    assert (
        pbi.download_source_url(Version("1.0.2"))
        == "https://egg.test/test-pkg/v1.0.2.tar.gz"
    )
    assert (
        pbi.download_source_destination_filename(
            Version("1.0.2"), resolve_template=False
        )
        == "${canonicalized_name}-${version}.tar.gz"
    )
    assert (
        pbi.download_source_destination_filename(Version("1.0.2"))
        == "test-pkg-1.0.2.tar.gz"
    )
    assert pbi.resolver_include_sdists is True
    assert pbi.resolver_include_wheels is False
    assert (
        pbi.resolver_sdist_server_url("https://pypi.org/simple")
        == "https://sdist.test/egg"
    )
    assert pbi.build_tag(Version("1.0.2")) == (2, "")
    sdist_root_dir = pathlib.Path("/sdist-root")
    assert pbi.build_dir(sdist_root_dir) == sdist_root_dir / "python"

    patchdir = test_settings.patches_dir / f"{TEST_PKG.replace('-', '_')}-1.0.2"
    assert pbi.get_patches() == {
        Version("1.0.2"): [
            patchdir / "001-somepatch.patch",
            patchdir / "002-otherpatch.patch",
        ],
    }
    assert pbi.get_patches() is pbi.get_patches()


def test_pbi_other(test_settings: Settings) -> None:
    pbi = test_settings.package_build_info(TEST_OTHER_PKG)
    assert pbi.package == NormalizedName(TEST_OTHER_PKG)
    assert pbi.variant == Variant(test_settings.variant)
    assert pbi.pre_built is False
    assert pbi.has_config is False
    assert pbi.wheel_server_url is None
    assert pbi.override_module_name == "test_other_pkg"
    assert pbi.download_source_url(Version("1.0.0")) is None
    assert pbi.download_source_destination_filename(Version("1.0.0")) is None
    assert pbi.download_source_destination_filename(Version("1.0.0")) is None
    assert pbi.resolver_include_sdists is True
    assert pbi.resolver_include_wheels is False
    assert (
        pbi.resolver_sdist_server_url("https://pypi.org/simple")
        == "https://pypi.org/simple"
    )
    assert pbi.build_tag(Version("1.0.0")) == ()
    sdist_root_dir = pathlib.Path("/sdist-root")
    assert pbi.build_dir(sdist_root_dir) == sdist_root_dir

    patchdir = test_settings.patches_dir / f"{TEST_OTHER_PKG.replace('-', '_')}-1.0.0"
    assert pbi.get_patches() == {
        Version("1.0.0"): [
            patchdir / "001-mypatch.patch",
        ],
    }
    assert pbi.get_patches() is pbi.get_patches()


def test_type_envvars():
    ta = pydantic.TypeAdapter(EnvVars)
    v = ta.validate_python(
        {"int": 1, "float": 2.0, "true": True, "false": False, "str": "string"}
    )
    assert v == {
        "int": "1",
        "float": "2.0",
        "true": "1",
        "false": "0",
        "str": "string",
    }
    with pytest.raises(ValueError):
        ta.validate_python({"shell": "$(subshell)"})
    with pytest.raises(TypeError):
        ta.validate_python({"none": None})


def test_type_package():
    ta = pydantic.TypeAdapter(Package)
    assert ta.validate_python("Some_Package") == "some-package"
    assert ta.validate_python("some.package") == "some-package"
    with pytest.raises(ValueError):
        ta.validate_python("invalid/package")


def test_type_builddirectory():
    ta = pydantic.TypeAdapter(BuildDirectory)
    assert ta.validate_python("python") == pathlib.Path("python")
    assert ta.validate_python("../tmp/build") == pathlib.Path("../tmp/build")
    with pytest.raises(ValueError):
        ta.validate_python("/absolute/path")


def test_global_settings(testdata_path: pathlib.Path):
    filename = testdata_path / "context/overrides/settings.yaml"
    gs = SettingsFile.from_file(filename)
    assert gs.changelog == {
        "testglobal": [
            "setuptools upgraded to 82.0.0",
        ],
    }


def test_settings_overrides(test_settings: Settings) -> None:
    assert test_settings.list_overrides() == {TEST_PKG, TEST_EMPTY_PKG, TEST_OTHER_PKG}


def test_global_changelog(test_settings: Settings) -> None:
    pbi = test_settings.package_build_info(TEST_PKG)
    assert pbi.variant == "cpu"
    assert pbi.build_tag(Version("0.99")) == ()
    assert pbi.build_tag(Version("1.0.1")) == (1, "")
    assert pbi.build_tag(Version("1.0.2")) == (2, "")
    assert pbi.build_tag(Version("2.0.0")) == ()

    test_settings.variant = Variant("testglobal")
    pbi = test_settings.package_build_info(TEST_PKG)
    assert pbi.variant == "testglobal"
    assert pbi.build_tag(Version("0.99")) == (1, "")
    assert pbi.build_tag(Version("1.0.1")) == (2, "")
    assert pbi.build_tag(Version("1.0.2")) == (3, "")
    assert pbi.build_tag(Version("2.0.0")) == (1, "")
