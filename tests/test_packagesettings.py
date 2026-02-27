import pathlib
import typing
from unittest.mock import Mock, patch

import pydantic
import pytest
from packaging.requirements import Requirement
from packaging.utils import NormalizedName
from packaging.version import Version

from fromager import build_environment, context
from fromager.packagesettings import (
    Annotations,
    BuildDirectory,
    CreateFile,
    EnvVars,
    GitOptions,
    Package,
    PackageSettings,
    ResolverDist,
    SettingsFile,
    Variant,
    substitute_template,
)

TEST_PKG = "test-pkg"
TEST_EMPTY_PKG = "test-empty-pkg"
TEST_OTHER_PKG = "test-other-pkg"
TEST_RELATED_PKG = "test-pkg-library"
TEST_PREBUILT_PKG = "test-prebuilt-pkg"

FULL_EXPECTED: dict[str, typing.Any] = {
    "annotations": {
        "fromager.test.value": "somevalue",
        "fromager.test.override": "variant override",
    },
    "build_dir": pathlib.Path("python"),
    "build_options": {
        "build_ext_parallel": True,
        "cpu_cores_per_job": 4,
        "memory_per_job_gb": 4.0,
        "exclusive_build": False,
    },
    "changelog": {
        Version("1.0.1"): ["fixed bug"],
        Version("1.0.2"): ["more bugs", "rebuild"],
    },
    "config_settings": {
        "setup-args": [
            "-Dsystem-freetype=true",
            "-Dsystem-qhull=true",
        ],
        "cmake.define.BLA_VENDOR": "OpenBLAS",
    },
    "create_files": [],
    "download_source": {
        "destination_filename": "${canonicalized_name}-${version}.tar.gz",
        "url": "https://egg.test/${canonicalized_name}/v${version}.tar.gz",
    },
    "env": {
        "EGG": "spam",
        "EGG_AGAIN": "$EGG",
        "SPAM": "alot $EXTRA",
        "QUOTES": "A\"BC'$$EGG",
        "DEF": "${DEF:-default}",
        "EXTRA_MAX_JOBS": "${MAX_JOBS}",
    },
    "git_options": {
        "submodules": False,
        "submodule_paths": [],
    },
    "name": "test-pkg",
    "has_config": True,
    "project_override": {
        "remove_build_requires": ["cmake"],
        "update_build_requires": ["setuptools>=68.0.0", "torch"],
        "requires_external": ["openssl-libs"],
        "update_install_requires": [],
        "remove_install_requires": [],
    },
    "resolver_dist": {
        "include_sdists": True,
        "include_wheels": True,
        "sdist_server_url": "https://sdist.test/egg",
        "ignore_platform": True,
        "use_pypi_org_metadata": True,
        "provider": None,
        "organization": None,
        "repo": None,
        "project_path": None,
        "server_url": None,
        "tag_matcher": None,
    },
    "variants": {
        "cpu": {
            "annotations": {
                "fromager.test.override": "cpu override",
            },
            "env": {"EGG": "spam ${EGG}", "EGG_AGAIN": "$EGG"},
            "wheel_server_url": "https://wheel.test/simple",
            "pre_built": False,
        },
        "rocm": {
            "annotations": {
                "fromager.test.override": "amd override",
            },
            "env": {"SPAM": ""},
            "wheel_server_url": None,
            "pre_built": True,
        },
        "cuda": {
            "annotations": None,
            "env": {},
            "wheel_server_url": None,
            "pre_built": False,
        },
    },
    "vendor_rust_before_patch": False,
}

EMPTY_EXPECTED: dict[str, typing.Any] = {
    "name": "test-empty-pkg",
    "annotations": None,
    "build_dir": None,
    "build_options": {
        "build_ext_parallel": False,
        "cpu_cores_per_job": 1,
        "memory_per_job_gb": 1.0,
        "exclusive_build": False,
    },
    "changelog": {},
    "config_settings": {},
    "create_files": [],
    "env": {},
    "download_source": {
        "url": None,
        "destination_filename": None,
    },
    "git_options": {
        "submodules": False,
        "submodule_paths": [],
    },
    "has_config": True,
    "project_override": {
        "remove_build_requires": [],
        "update_build_requires": [],
        "requires_external": [],
        "update_install_requires": [],
        "remove_install_requires": [],
    },
    "resolver_dist": {
        "sdist_server_url": None,
        "include_sdists": True,
        "include_wheels": False,
        "ignore_platform": False,
        "use_pypi_org_metadata": None,
        "provider": None,
        "organization": None,
        "repo": None,
        "project_path": None,
        "server_url": None,
        "tag_matcher": None,
    },
    "variants": {},
    "vendor_rust_before_patch": False,
}

PREBUILT_PKG_EXPECTED: dict[str, typing.Any] = {
    "name": "test-prebuilt-pkg",
    "annotations": None,
    "build_dir": None,
    "build_options": {
        "build_ext_parallel": False,
        "cpu_cores_per_job": 1,
        "memory_per_job_gb": 1.0,
        "exclusive_build": False,
    },
    "changelog": {
        Version("1.0.1"): ["onboard"],
    },
    "config_settings": {},
    "create_files": [],
    "env": {},
    "download_source": {
        "url": None,
        "destination_filename": None,
    },
    "git_options": {
        "submodules": False,
        "submodule_paths": [],
    },
    "has_config": True,
    "project_override": {
        "remove_build_requires": [],
        "update_build_requires": [],
        "requires_external": [],
        "update_install_requires": [],
        "remove_install_requires": [],
    },
    "resolver_dist": {
        "sdist_server_url": None,
        "include_sdists": True,
        "include_wheels": False,
        "ignore_platform": False,
        "use_pypi_org_metadata": None,
        "provider": None,
        "organization": None,
        "repo": None,
        "project_path": None,
        "server_url": None,
        "tag_matcher": None,
    },
    "variants": {
        "cpu": {
            "annotations": None,
            "env": {},
            "pre_built": True,
            "wheel_server_url": None,
        },
    },
    "vendor_rust_before_patch": False,
}


def test_parse_full(testdata_path: pathlib.Path) -> None:
    filename = testdata_path / "context/overrides/settings/test_pkg.yaml"
    p = PackageSettings.from_string(TEST_PKG, filename.read_text())
    assert p.model_dump() == FULL_EXPECTED


def test_parse_full_file(testdata_path: pathlib.Path) -> None:
    filename = testdata_path / "context/overrides/settings/test_pkg.yaml"
    p = PackageSettings.from_file(filename)
    assert p.model_dump() == FULL_EXPECTED


def test_parse_minimal(testdata_path: pathlib.Path) -> None:
    filename = testdata_path / "context/overrides/settings/test_empty_pkg.yaml"
    p = PackageSettings.from_string(TEST_EMPTY_PKG, filename.read_text())
    assert p.model_dump() == EMPTY_EXPECTED


def test_parse_minimal_file(testdata_path: pathlib.Path) -> None:
    filename = testdata_path / "context/overrides/settings/test_empty_pkg.yaml"
    p = PackageSettings.from_file(filename)
    assert p.model_dump() == EMPTY_EXPECTED


def test_parse_prebuilt_file(testdata_path: pathlib.Path) -> None:
    filename = testdata_path / "context/overrides/settings/test_prebuilt_pkg.yaml"
    p = PackageSettings.from_file(filename)
    assert p.model_dump() == PREBUILT_PKG_EXPECTED


def test_default_settings() -> None:
    p = PackageSettings.from_default(TEST_EMPTY_PKG)
    expected = EMPTY_EXPECTED.copy()
    expected["has_config"] = False
    assert p.model_dump() == expected


def test_pbi_test_pkg_extra_environ(
    tmp_path: pathlib.Path, testdata_context: context.WorkContext
) -> None:
    testdata_context.settings.max_jobs = 1
    parallel = {
        "CMAKE_BUILD_PARALLEL_LEVEL": "1",
        "MAKEFLAGS": "-j1",
        "MAX_JOBS": "1",
        "EXTRA_MAX_JOBS": "1",
    }

    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    assert (
        pbi.get_extra_environ(template_env={"EXTRA": "extra"})
        == {
            "EGG": "spam spam",
            "EGG_AGAIN": "spam spam",
            "QUOTES": "A\"BC'$EGG",  # $$EGG is transformed into $EGG
            "SPAM": "alot extra",
            "DEF": "default",
        }
        | parallel
    )
    assert (
        pbi.get_extra_environ(template_env={"EXTRA": "extra", "DEF": "nondefault"})
        == {
            "EGG": "spam spam",
            "EGG_AGAIN": "spam spam",
            "QUOTES": "A\"BC'$EGG",  # $$EGG is transformed into $EGG
            "SPAM": "alot extra",
            "DEF": "nondefault",
        }
        | parallel
    )

    testdata_context.settings.variant = Variant("rocm")
    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    assert (
        pbi.get_extra_environ(template_env={"EXTRA": "extra"})
        == {
            "EGG": "spam",
            "EGG_AGAIN": "spam",
            "QUOTES": "A\"BC'$EGG",
            "SPAM": "",
            "DEF": "default",
        }
        | parallel
    )

    testdata_context.settings.variant = Variant("cuda")
    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    assert (
        pbi.get_extra_environ(template_env={"EXTRA": "spam"})
        == {
            "EGG": "spam",
            "EGG_AGAIN": "spam",
            "QUOTES": "A\"BC'$EGG",
            "SPAM": "alot spam",
            "DEF": "default",
        }
        | parallel
    )

    build_env = build_environment.BuildEnvironment(
        testdata_context,
        parent_dir=tmp_path,
    )
    result = pbi.get_extra_environ(
        template_env={"EXTRA": "spam", "PATH": "/sbin:/bin"}, build_env=build_env
    )
    assert (
        result
        == {
            "EGG": "spam",
            "EGG_AGAIN": "spam",
            "QUOTES": "A\"BC'$EGG",
            "SPAM": "alot spam",
            "DEF": "default",
            "PATH": f"{build_env.path / 'bin'}:/sbin:/bin",
            "VIRTUAL_ENV": str(build_env.path),
            "UV_CACHE_DIR": str(testdata_context.uv_cache),
            "UV_NATIVE_TLS": "true",
            "UV_NO_MANAGED_PYTHON": "true",
            "UV_PYTHON": str(build_env.python),
            "UV_PYTHON_DOWNLOADS": "never",
        }
        | parallel
    )


def test_pbi_test_pkg(testdata_context: context.WorkContext) -> None:
    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    assert pbi.package == NormalizedName(TEST_PKG)
    assert pbi.variant == Variant(testdata_context.settings.variant)
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
    assert pbi.resolver_include_wheels is True
    assert pbi.resolver_ignore_platform is True
    assert (
        pbi.resolver_sdist_server_url("https://pypi.org/simple")
        == "https://sdist.test/egg"
    )
    assert pbi.build_tag(Version("1.0.2")) == (2, "")
    sdist_root_dir = pathlib.Path("/sdist-root")
    assert pbi.build_dir(sdist_root_dir) == sdist_root_dir / "python"


def test_pbi_test_pkg_patches(testdata_context: context.WorkContext) -> None:
    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    norm_test_pkg = TEST_PKG.replace("-", "_")
    unversioned_patchdir = testdata_context.settings.patches_dir / norm_test_pkg
    versioned_patchdir = (
        testdata_context.settings.patches_dir / f"{norm_test_pkg}-1.0.2"
    )

    patch001 = versioned_patchdir / "001-somepatch.patch"
    patch002 = versioned_patchdir / "002-otherpatch.patch"
    patch004 = unversioned_patchdir / "cpu" / "004-cpu.patch"
    patch005 = versioned_patchdir / "cpu" / "005-cpuver.patch"
    patch010 = unversioned_patchdir / "010-unversioned.patch"

    assert pbi.get_all_patches() == {
        None: [patch004, patch010],
        Version("1.0.2"): [patch001, patch002, patch005],
    }
    assert pbi.get_all_patches() is pbi.get_all_patches()

    assert pbi.get_patches(Version("1.0.2")) == [
        patch001,
        patch002,
        patch004,
        patch005,
        patch010,
    ]
    assert pbi.get_patches(Version("1.0.2+local")) == pbi.get_patches(Version("1.0.2"))
    assert pbi.get_patches(Version("1.0.1")) == [
        patch004,
        patch010,
    ]


def test_pbi_other(testdata_context: context.WorkContext) -> None:
    pbi = testdata_context.settings.package_build_info(TEST_OTHER_PKG)
    assert pbi.package == NormalizedName(TEST_OTHER_PKG)
    assert pbi.variant == Variant(testdata_context.settings.variant)
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

    patchdir = (
        testdata_context.settings.patches_dir
        / f"{TEST_OTHER_PKG.replace('-', '_')}-1.0.0"
    )
    assert pbi.get_all_patches() == {
        Version("1.0.0"): [
            patchdir / "001-mypatch.patch",
        ],
    }
    assert pbi.get_all_patches() is pbi.get_all_patches()


def test_type_envvars() -> None:
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


def test_type_package() -> None:
    ta = pydantic.TypeAdapter(Package)
    assert ta.validate_python("Some_Package") == "some-package"
    assert ta.validate_python("some.package") == "some-package"
    with pytest.raises(ValueError):
        ta.validate_python("invalid/package")


def test_type_builddirectory() -> None:
    ta = pydantic.TypeAdapter(BuildDirectory)
    assert ta.validate_python("python") == pathlib.Path("python")
    assert ta.validate_python("../tmp/build") == pathlib.Path("../tmp/build")
    with pytest.raises(ValueError):
        ta.validate_python("/absolute/path")


def test_global_settings(testdata_path: pathlib.Path) -> None:
    filename = testdata_path / "context/overrides/settings.yaml"
    gs = SettingsFile.from_file(filename)
    assert gs.changelog == {
        "rocm": [
            "setuptools upgraded to 82.0.0",
        ],
    }


def test_settings_overrides(testdata_context: context.WorkContext) -> None:
    assert testdata_context.settings.list_overrides() == {
        TEST_PKG,
        TEST_EMPTY_PKG,
        TEST_OTHER_PKG,
        TEST_RELATED_PKG,
        TEST_PREBUILT_PKG,
    }


def test_global_changelog(testdata_context: context.WorkContext) -> None:
    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    assert pbi.package == TEST_PKG
    assert not pbi.pre_built
    assert pbi.variant == "cpu"
    assert pbi.build_tag(Version("0.99")) == ()
    assert pbi.build_tag(Version("1.0.1")) == (1, "")
    assert pbi.build_tag(Version("1.0.2")) == (2, "")
    assert pbi.build_tag(Version("1.0.2+local")) == pbi.build_tag(Version("1.0.2"))
    assert pbi.build_tag(Version("2.0.0")) == ()

    # CUDA variant has no global changelog
    testdata_context.settings.variant = Variant("cuda")
    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    assert pbi.package == TEST_PKG
    assert not pbi.pre_built
    assert pbi.variant == "cuda"
    assert pbi.build_tag(Version("0.99")) == ()
    assert pbi.build_tag(Version("1.0.1")) == (1, "")
    assert pbi.build_tag(Version("1.0.2")) == (2, "")
    assert pbi.build_tag(Version("1.0.2+local")) == pbi.build_tag(Version("1.0.2"))
    assert pbi.build_tag(Version("2.0.0")) == ()

    # ROCm variant has pre-built flag
    testdata_context.settings.variant = Variant("rocm")
    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    assert pbi.package == TEST_PKG
    assert pbi.pre_built
    assert pbi.variant == "rocm"
    assert pbi.build_tag(Version("0.99")) == ()

    testdata_context.settings.variant = Variant("cpu")
    pbi = testdata_context.settings.package_build_info(TEST_PREBUILT_PKG)
    assert pbi.package == TEST_PREBUILT_PKG
    assert pbi.pre_built
    assert pbi.variant == "cpu"
    assert pbi.get_changelog(Version("1.0.1")) == ["onboard"]
    assert pbi.build_tag(Version("1.0.1")) == ()


def test_settings_list(testdata_context: context.WorkContext) -> None:
    assert testdata_context.settings.list_overrides() == {
        TEST_EMPTY_PKG,
        TEST_OTHER_PKG,
        TEST_PKG,
        TEST_RELATED_PKG,
        TEST_PREBUILT_PKG,
    }
    assert testdata_context.settings.list_pre_built() == {TEST_PREBUILT_PKG}
    assert testdata_context.settings.variant_changelog() == []
    testdata_context.settings.variant = Variant("rocm")
    assert testdata_context.settings.list_pre_built() == {TEST_PKG}
    assert testdata_context.settings.variant_changelog() == [
        "setuptools upgraded to 82.0.0"
    ]


@patch("fromager.packagesettings.get_cpu_count", return_value=8)
@patch("fromager.packagesettings.get_available_memory_gib", return_value=7.1)
def test_parallel_jobs(
    get_available_memory_gib: Mock,
    get_cpu_count: Mock,
    testdata_context: context.WorkContext,
) -> None:
    assert testdata_context.settings.max_jobs is None

    pbi = testdata_context.settings.package_build_info(TEST_EMPTY_PKG)
    assert pbi.parallel_jobs() == 7

    get_cpu_count.return_value = 4
    assert pbi.parallel_jobs() == 4

    get_available_memory_gib.return_value = 2.1
    assert pbi.parallel_jobs() == 2

    get_available_memory_gib.return_value = 1.5
    assert pbi.parallel_jobs() == 1

    testdata_context.settings.max_jobs = 2
    pbi = testdata_context.settings.package_build_info(TEST_EMPTY_PKG)
    get_available_memory_gib.return_value = 23
    assert pbi.parallel_jobs() == 2

    # test-pkg needs more memory
    testdata_context.settings.max_jobs = 200
    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    get_cpu_count.return_value = 16
    get_available_memory_gib.return_value = 20
    assert pbi.parallel_jobs() == 4

    get_cpu_count.return_value = 32
    get_available_memory_gib.return_value = 25
    assert pbi.parallel_jobs() == 6

    testdata_context.settings.max_jobs = 4
    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    assert pbi.parallel_jobs() == 4


@pytest.mark.parametrize(
    "value,template_env,expected",
    [
        ("", {}, ""),
        ("${var}", {"var": "value"}, "value"),
        ("$${var}", {"var": "value"}, "${var}"),
        ("${var:-}", {}, ""),
        ("${var:-default}", {}, "default"),
        ("${var:-default}", {"var": "value"}, "value"),
        ("$${var:-default}", {}, "${var:-default}"),
    ],
)
def test_substitute_template(
    value: str, template_env: dict[str, str], expected: str
) -> None:
    assert substitute_template(value, template_env) == expected


def test_substitute_template_key_error() -> None:
    # This test expects a ValueError to be raised by substitute_template
    with pytest.raises(ValueError) as excinfo:
        substitute_template("${DEFAULT:-default} ${UNKNOWN}", {})
    # Verify that the error message matches the expected message
    assert (
        str(excinfo.value)
        == "Undefined environment variable KeyError('UNKNOWN') referenced in expression '${DEFAULT} ${UNKNOWN}'"
    )


def test_git_options_default() -> None:
    """Test that GitOptions has correct default values."""
    git_opts = GitOptions()
    assert git_opts.submodules is False
    assert git_opts.submodule_paths == []


def test_git_options_with_submodules_enabled() -> None:
    """Test GitOptions with submodules enabled."""
    git_opts = GitOptions(submodules=True)
    assert git_opts.submodules is True
    assert git_opts.submodule_paths == []


def test_git_options_with_specific_paths() -> None:
    """Test GitOptions with specific submodule paths."""
    paths = ["vendor/lib1", "vendor/lib2"]
    git_opts = GitOptions(submodule_paths=paths)
    assert git_opts.submodules is False  # Default value
    assert git_opts.submodule_paths == paths


def test_git_options_with_both_settings() -> None:
    """Test GitOptions with both submodules and paths configured."""
    paths = ["vendor/lib1"]
    git_opts = GitOptions(submodules=True, submodule_paths=paths)
    assert git_opts.submodules is True
    assert git_opts.submodule_paths == paths


def test_package_settings_git_options_default() -> None:
    """Test that PackageSettings includes GitOptions with defaults."""
    settings = PackageSettings.from_default("test-pkg")
    assert hasattr(settings, "git_options")
    assert isinstance(settings.git_options, GitOptions)
    assert settings.git_options.submodules is False
    assert settings.git_options.submodule_paths == []


def test_package_settings_git_options_from_dict() -> None:
    """Test PackageSettings can parse git_options from dictionary."""
    settings = PackageSettings.model_validate(
        {
            "name": "test-pkg",
            "has_config": True,
            "git_options": {
                "submodules": True,
            },
        }
    )
    assert settings.git_options.submodules is True
    assert settings.git_options.submodule_paths == []  # Default value


def test_package_settings_git_options_from_dict_empty() -> None:
    """Test PackageSettings can parse empty git_options from dictionary."""
    settings = PackageSettings.model_validate(
        {"name": "test-pkg", "has_config": True, "git_options": {}}
    )
    assert settings.git_options.submodules is False  # Default value
    assert settings.git_options.submodule_paths == []  # Default value


def test_package_settings_git_options_from_file() -> None:
    """Test PackageSettings can parse git_options from a YAML file."""
    data = """
git_options:
  submodules: true
  submodule_paths:
    - path/to/submodule
"""
    settings = PackageSettings.from_string("test-pkg", data)
    assert settings.git_options.submodules is True
    assert settings.git_options.submodule_paths == ["path/to/submodule"]


def test_package_build_info_git_options(testdata_context: context.WorkContext) -> None:
    """Test that PackageBuildInfo exposes git_options property."""
    req = Requirement("test-pkg==1.0.0")
    pbi = testdata_context.package_build_info(req)

    # Check that git_options property exists and returns GitOptions
    assert hasattr(pbi, "git_options")
    git_opts = pbi.git_options
    assert isinstance(git_opts, GitOptions)

    # Test that default values are correct
    assert git_opts.submodules is False
    assert git_opts.submodule_paths == []

    # Test creating a new package settings with custom git options
    settings_yaml = """
git_options:
  submodules: true
  submodule_paths:
    - vendor/lib
"""
    custom_settings = PackageSettings.from_string("custom-pkg", settings_yaml)
    assert custom_settings.git_options.submodules is True
    assert custom_settings.git_options.submodule_paths == ["vendor/lib"]


def test_package_build_info_exclusive_build(
    testdata_context: context.WorkContext,
) -> None:
    """Test that PackageBuildInfo correctly exposes exclusive_build from build_options."""
    # Test default package (should have exclusive_build=False by default)
    req = Requirement("test-empty-pkg==1.0.0")
    pbi = testdata_context.package_build_info(req)
    assert pbi.exclusive_build is False

    # Test creating a package settings with exclusive_build=True
    settings_yaml = """
build_options:
  exclusive_build: true
"""
    custom_settings = PackageSettings.from_string("exclusive-pkg", settings_yaml)
    assert custom_settings.build_options.exclusive_build is True

    # Test PackageBuildInfo properly accesses it through build_options
    import pathlib

    from fromager.packagesettings import Settings, SettingsFile

    # Create a temporary Settings object to test with
    settings = Settings(
        settings=SettingsFile(),
        package_settings=[custom_settings],
        variant="cpu",
        patches_dir=pathlib.Path("/tmp"),
        max_jobs=1,
    )

    custom_pbi = settings.package_build_info("exclusive-pkg")
    assert custom_pbi.exclusive_build is True


def test_resolver_dist_validator() -> None:
    with pytest.raises(pydantic.ValidationError):
        ResolverDist(include_wheels=False, ignore_platform=True)


def test_annotation_type() -> None:
    ann = Annotations(None, None)
    assert not ann
    assert len(ann) == 0
    assert ann == {}
    with pytest.raises(TypeError):
        ann["key"] = "value"  # type: ignore

    ann = Annotations({"ka": "va", "kb": "vb"}, {"kb": "otherb", "kc": "vc"})
    assert ann
    assert len(ann) == 3
    assert ann == {"ka": "va", "kb": "otherb", "kc": "vc"}

    ann = Annotations({"t": "yes", "f": "no", "invalid": "invalid"}, {})
    assert ann.getbool("t") is True
    assert ann.getbool("f") is False
    with pytest.raises(ValueError):
        ann.getbool("invalid")
    with pytest.raises(KeyError):
        ann.getbool("missing")


def test_pbi_annotations(testdata_context: context.WorkContext) -> None:
    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    assert pbi.annotations == {
        "fromager.test.value": "somevalue",
        "fromager.test.override": "cpu override",
    }

    testdata_context.settings.variant = Variant("cuda")
    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    assert pbi.annotations == {
        "fromager.test.value": "somevalue",
        "fromager.test.override": "variant override",
    }

    testdata_context.settings.variant = Variant("rocm")
    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    assert pbi.annotations == {
        "fromager.test.value": "somevalue",
        "fromager.test.override": "amd override",
    }

    pbi = testdata_context.settings.package_build_info(TEST_EMPTY_PKG)
    assert pbi.annotations == {}


def test_use_pypi_org_metadata(testdata_context: context.WorkContext) -> None:
    pbi = testdata_context.settings.package_build_info(TEST_PKG)
    assert pbi.use_pypi_org_metadata

    pbi = testdata_context.settings.package_build_info(TEST_EMPTY_PKG)
    assert not pbi.use_pypi_org_metadata

    pbi = testdata_context.settings.package_build_info(
        "somepackage_without_customization"
    )
    assert pbi.use_pypi_org_metadata


@patch("fromager.packagesettings.get_cpu_count", return_value=1)
@patch("fromager.packagesettings.get_available_memory_gib", return_value=8.0)
def test_get_extra_environ_version_substitution(
    _get_mem: Mock,
    _get_cpu: Mock,
) -> None:
    """Verify ${version} template vars are substituted in env settings."""
    settings_yaml = """
env:
    MY_VERSION: "${version}"
    MY_BASE: "${version_base_version}"
    MY_POST: "${version_post}"
"""
    from fromager.packagesettings import Settings, SettingsFile

    ps = PackageSettings.from_string("version-pkg", settings_yaml)
    s = Settings(
        settings=SettingsFile(),
        package_settings=[ps],
        variant="cpu",
        patches_dir=pathlib.Path("/tmp"),
        max_jobs=1,
    )
    pbi = s.package_build_info("version-pkg")
    result = pbi.get_extra_environ(template_env={}, version=Version("1.2.3"))
    assert result["MY_VERSION"] == "1.2.3"
    assert result["MY_BASE"] == "1.2.3"
    assert result["MY_POST"] == ""


@patch("fromager.packagesettings.get_cpu_count", return_value=1)
@patch("fromager.packagesettings.get_available_memory_gib", return_value=8.0)
def test_get_extra_environ_version_post_release(
    _get_mem: Mock,
    _get_cpu: Mock,
) -> None:
    """Verify ${version_base_version} and ${version_post} with post-release."""
    settings_yaml = """
env:
    MY_VERSION: "${version}"
    MY_BASE: "${version_base_version}"
    MY_POST: "${version_post}"
"""
    from fromager.packagesettings import Settings, SettingsFile

    ps = PackageSettings.from_string("version-pkg", settings_yaml)
    s = Settings(
        settings=SettingsFile(),
        package_settings=[ps],
        variant="cpu",
        patches_dir=pathlib.Path("/tmp"),
        max_jobs=1,
    )
    pbi = s.package_build_info("version-pkg")
    result = pbi.get_extra_environ(template_env={}, version=Version("1.2.3.post1"))
    assert result["MY_VERSION"] == "1.2.3.post1"
    assert result["MY_BASE"] == "1.2.3"
    assert result["MY_POST"] == "1"


@patch("fromager.packagesettings.get_cpu_count", return_value=1)
@patch("fromager.packagesettings.get_available_memory_gib", return_value=8.0)
def test_get_extra_environ_version_none_backward_compat(
    _get_mem: Mock,
    _get_cpu: Mock,
    testdata_context: context.WorkContext,
) -> None:
    """Verify backward compatibility when version is None."""
    testdata_context.settings.max_jobs = 1
    pbi = testdata_context.settings.package_build_info(TEST_EMPTY_PKG)
    result = pbi.get_extra_environ(template_env={}, version=None)
    assert "version" not in result
    assert "version_base_version" not in result
    assert "version_post" not in result


@patch("fromager.packagesettings.get_cpu_count", return_value=1)
@patch("fromager.packagesettings.get_available_memory_gib", return_value=8.0)
def test_get_extra_environ_version_env_override(
    _get_mem: Mock,
    _get_cpu: Mock,
) -> None:
    """Verify that actual env variables named 'version' take precedence."""
    settings_yaml = """
env:
    MY_VERSION: "${version}"
"""
    from fromager.packagesettings import Settings, SettingsFile

    ps = PackageSettings.from_string("version-pkg", settings_yaml)
    s = Settings(
        settings=SettingsFile(),
        package_settings=[ps],
        variant="cpu",
        patches_dir=pathlib.Path("/tmp"),
        max_jobs=1,
    )
    pbi = s.package_build_info("version-pkg")
    result = pbi.get_extra_environ(
        template_env={"version": "from-env"},
        version=Version("1.2.3"),
    )
    assert result["MY_VERSION"] == "from-env"


def test_create_file_relative_path() -> None:
    """Verify CreateFile accepts relative paths."""
    cf = CreateFile(path="src/mypackage/__init__.py", content="")
    assert cf.path == "src/mypackage/__init__.py"
    assert cf.content == ""


def test_create_file_rejects_absolute_path() -> None:
    """Verify CreateFile rejects absolute paths."""
    with pytest.raises(pydantic.ValidationError, match="is not a relative path"):
        CreateFile(path="/etc/passwd", content="bad")


def test_create_file_rejects_path_traversal() -> None:
    """Verify CreateFile rejects paths with '..' components."""
    with pytest.raises(pydantic.ValidationError, match="must not contain"):
        CreateFile(path="../../../etc/passwd", content="bad")

    with pytest.raises(pydantic.ValidationError, match="must not contain"):
        CreateFile(path="src/../../etc/passwd", content="bad")


def test_create_file_with_content() -> None:
    """Verify CreateFile stores content."""
    cf = CreateFile(path="version.py", content='__version__ = "${version}"')
    assert cf.content == '__version__ = "${version}"'


def test_vendor_rust_before_patch_default() -> None:
    """Verify vendor_rust_before_patch defaults to False."""
    settings = PackageSettings.from_default("test-pkg")
    assert settings.vendor_rust_before_patch is False


def test_vendor_rust_before_patch_from_yaml() -> None:
    """Verify vendor_rust_before_patch can be set via YAML."""
    data = "vendor_rust_before_patch: true\n"
    settings = PackageSettings.from_string("test-pkg", data)
    assert settings.vendor_rust_before_patch is True


def test_create_files_from_yaml() -> None:
    """Verify create_files can be parsed from YAML."""
    data = """\
create_files:
  - path: src/mypackage/__init__.py
    content: ""
  - path: src/mypackage/version.py
    content: |
      __version__ = "${version}"
"""
    settings = PackageSettings.from_string("test-pkg", data)
    assert len(settings.create_files) == 2
    assert settings.create_files[0].path == "src/mypackage/__init__.py"
    assert settings.create_files[0].content == ""
    assert settings.create_files[1].path == "src/mypackage/version.py"
    assert '__version__ = "${version}"' in settings.create_files[1].content


def test_pbi_vendor_rust_before_patch() -> None:
    """Verify PackageBuildInfo exposes vendor_rust_before_patch."""
    from fromager.packagesettings import Settings, SettingsFile

    data = "vendor_rust_before_patch: true\n"
    ps = PackageSettings.from_string("test-pkg", data)
    settings = Settings(
        settings=SettingsFile(),
        package_settings=[ps],
        variant="cpu",
        patches_dir=pathlib.Path("/tmp"),
        max_jobs=1,
    )
    pbi = settings.package_build_info("test-pkg")
    assert pbi.vendor_rust_before_patch is True


def test_pbi_create_files() -> None:
    """Verify PackageBuildInfo exposes create_files."""
    from fromager.packagesettings import Settings, SettingsFile

    data = """\
create_files:
  - path: src/__init__.py
    content: ""
"""
    ps = PackageSettings.from_string("test-pkg", data)
    settings = Settings(
        settings=SettingsFile(),
        package_settings=[ps],
        variant="cpu",
        patches_dir=pathlib.Path("/tmp"),
        max_jobs=1,
    )
    pbi = settings.package_build_info("test-pkg")
    assert len(pbi.create_files) == 1
    assert pbi.create_files[0].path == "src/__init__.py"


def test_resolver_dist_github_provider() -> None:
    """Verify ResolverDist accepts valid github provider config."""
    rd = ResolverDist(provider="github", organization="myorg", repo="myrepo")
    assert rd.provider == "github"
    assert rd.organization == "myorg"
    assert rd.repo == "myrepo"


def test_resolver_dist_github_provider_missing_fields() -> None:
    """Verify github provider requires organization and repo."""
    with pytest.raises(pydantic.ValidationError, match="organization.*repo"):
        ResolverDist(provider="github", organization="myorg")
    with pytest.raises(pydantic.ValidationError, match="organization.*repo"):
        ResolverDist(provider="github", repo="myrepo")
    with pytest.raises(pydantic.ValidationError, match="organization.*repo"):
        ResolverDist(provider="github")


def test_resolver_dist_gitlab_provider_with_project_path() -> None:
    """Verify GitLab provider with project_path."""
    rd = ResolverDist(provider="gitlab", project_path="group/subgroup/project")
    assert rd.provider == "gitlab"
    assert rd.project_path == "group/subgroup/project"


def test_resolver_dist_gitlab_provider_with_org_repo() -> None:
    """Verify GitLab provider with organization and repo."""
    rd = ResolverDist(provider="gitlab", organization="myorg", repo="myrepo")
    assert rd.provider == "gitlab"
    assert rd.organization == "myorg"
    assert rd.repo == "myrepo"


def test_resolver_dist_gitlab_provider_missing_fields() -> None:
    """Verify gitlab provider requires project_path or organization+repo."""
    with pytest.raises(pydantic.ValidationError, match="project_path"):
        ResolverDist(provider="gitlab")
    with pytest.raises(pydantic.ValidationError, match="project_path"):
        ResolverDist(provider="gitlab", organization="myorg")


def test_resolver_dist_unknown_provider() -> None:
    """Verify unknown provider names are rejected."""
    with pytest.raises(pydantic.ValidationError, match="Unknown provider"):
        ResolverDist(provider="unknown")


def test_resolver_dist_pypi_provider() -> None:
    """Verify pypi provider is accepted (explicit or default)."""
    rd = ResolverDist(provider="pypi")
    assert rd.provider == "pypi"
    rd_default = ResolverDist()
    assert rd_default.provider is None


def test_resolver_dist_tag_matcher_valid() -> None:
    """Verify valid tag_matcher regex with one capturing group."""
    rd = ResolverDist(
        provider="github",
        organization="org",
        repo="repo",
        tag_matcher=r"v(\d+\.\d+\.\d+)",
    )
    assert rd.tag_matcher == r"v(\d+\.\d+\.\d+)"


def test_resolver_dist_tag_matcher_invalid_regex() -> None:
    """Verify invalid regex in tag_matcher is rejected."""
    with pytest.raises(pydantic.ValidationError, match="Invalid tag_matcher regex"):
        ResolverDist(
            provider="github",
            organization="org",
            repo="repo",
            tag_matcher=r"v(\d+",
        )


def test_resolver_dist_tag_matcher_wrong_groups() -> None:
    """Verify tag_matcher with zero or multiple groups is rejected."""
    with pytest.raises(pydantic.ValidationError, match="exactly 1 capturing group"):
        ResolverDist(
            provider="github",
            organization="org",
            repo="repo",
            tag_matcher=r"v\d+\.\d+\.\d+",
        )
    with pytest.raises(pydantic.ValidationError, match="exactly 1 capturing group"):
        ResolverDist(
            provider="github",
            organization="org",
            repo="repo",
            tag_matcher=r"v(\d+)\.(\d+)",
        )


def test_resolver_dist_from_yaml() -> None:
    """Verify ResolverDist can be parsed from YAML via PackageSettings."""
    yaml_data = """
resolver_dist:
  provider: github
  organization: openssl
  repo: openssl
  tag_matcher: "openssl-(\\\\d+\\\\.\\\\d+\\\\.\\\\d+)"
"""
    ps = PackageSettings.from_string("test-resolver-pkg", yaml_data)
    assert ps.resolver_dist.provider == "github"
    assert ps.resolver_dist.organization == "openssl"
    assert ps.resolver_dist.repo == "openssl"


def test_pbi_resolver_properties() -> None:
    """Verify PackageBuildInfo exposes resolver properties."""
    from fromager.packagesettings import Settings, SettingsFile

    ps = PackageSettings.from_string(
        "resolver-test",
        """
resolver_dist:
  provider: github
  organization: myorg
  repo: myrepo
  tag_matcher: "v(.*)"
""",
    )
    settings = Settings(
        settings=SettingsFile(),
        package_settings=[ps],
        variant="cpu",
        patches_dir=pathlib.Path("/tmp"),
        max_jobs=1,
    )
    pbi = settings.package_build_info("resolver-test")
    assert pbi.resolver_provider == "github"
    assert pbi.resolver_organization == "myorg"
    assert pbi.resolver_repo == "myrepo"
    assert pbi.resolver_project_path is None
    assert pbi.resolver_server_url is None
    assert pbi.resolver_tag_matcher == "v(.*)"
