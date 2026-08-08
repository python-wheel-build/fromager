import pathlib

import pytest
import resolvelib
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import constraints, context, finders
from fromager.requirements_file import RequirementType


@pytest.mark.parametrize(
    "dist_name,version_string,expected_base",
    [
        ("mypkg", "1.2", "mypkg-1.2.tar.gz"),
        ("oslo.messaging", "14.7.0", "oslo.messaging-14.7.0.tar.gz"),
        ("cython", "3.0.10", "Cython-3.0.10.tar.gz"),
        ("fromage_test", "9.9.9", "fromage-test-9.9.9.tar.gz"),
        ("ruamel-yaml", "0.18.6", "ruamel.yaml-0.18.6.tar.gz"),
    ],
)
def test_find_sdist(
    tmp_path: pathlib.Path,
    tmp_context: context.WorkContext,
    dist_name: str,
    version_string: str,
    expected_base: str,
) -> None:
    sdists_repo = pathlib.Path(tmp_path)
    downloads = sdists_repo / "downloads"
    downloads.mkdir()
    archive = downloads / expected_base
    archive.write_text("not-empty")

    req = Requirement(dist_name)
    actual = finders.find_sdist(tmp_context, downloads, req, version_string)
    assert str(archive) == str(actual)


@pytest.mark.parametrize(
    "dist_name,version_string,expected_base",
    [
        ("mypkg", "1.2", "mypkg-1.2-py2.py3-none-any.whl"),
        ("oslo.messaging", "14.7.0", "oslo.messaging-14.7.0-py2.py3-none-any.whl"),
        ("cython", "3.0.10", "Cython-3.0.10-cp311-cp311-linux_aarch64.whl"),
        ("fromage_test", "9.9.9", "fromage-test-9.9.9-cp311-cp311-linux_aarch64.whl"),
        ("ruamel-yaml", "0.18.6", "ruamel.yaml-0.18.6-py3-none-any.whl"),
    ],
)
def test_find_wheel(
    tmp_path: pathlib.Path, dist_name: str, version_string: str, expected_base: str
) -> None:
    wheels_repo = pathlib.Path(tmp_path)
    downloads = wheels_repo / "downloads"
    downloads.mkdir()
    wheel = downloads / expected_base
    wheel.write_text("not-empty")

    req = Requirement(dist_name)
    actual = finders.find_wheel(downloads, req, version_string, ())
    assert str(wheel) == str(actual)


def test_find_wheel_ignores_non_wheel_files(tmp_path: pathlib.Path) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    wheel = downloads / "mypkg-1.2-py3-none-any.whl"
    wheel.write_text("not-empty")
    (downloads / "mypkg-1.2-py3-none-any.tar.gz").write_text("not-a-wheel")
    (downloads / "mypkg-1.2.metadata").write_text("not-a-wheel")

    req = Requirement("mypkg")
    actual = finders.find_wheel(downloads, req, "1.2", ())
    assert str(wheel) == str(actual)


def test_find_wheel_returns_none_when_only_non_wheel_files(
    tmp_path: pathlib.Path,
) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "mypkg-1.2-py3-none-any.tar.gz").write_text("not-a-wheel")
    (downloads / "mypkg-1.2.metadata").write_text("not-a-wheel")

    req = Requirement("mypkg")
    assert finders.find_wheel(downloads, req, "1.2", ()) is None


@pytest.mark.parametrize(
    "dist_name,version_string,unpack_base,source_base",
    [
        ("mypkg", "1.2", "mypkg-1.2", "mypkg-1.2"),
        ("oslo.messaging", "14.7.0", "oslo.messaging-14.7.0", "oslo.messaging-14.7.0"),
        ("cython", "3.0.10", "Cython-3.0.10", "Cython-3.0.10"),
        ("ruamel-yaml", "0.18.6", "ruamel.yaml-0.18.6", "ruamel.yaml-0.18.6"),
    ],
)
def test_find_source_dir(
    tmp_path: pathlib.Path,
    tmp_context: context.WorkContext,
    dist_name: str,
    version_string: str,
    unpack_base: str,
    source_base: str,
) -> None:
    work_dir = pathlib.Path(tmp_path)
    unpack_dir = work_dir / unpack_base
    unpack_dir.mkdir()
    source_dir = unpack_dir / source_base
    source_dir.mkdir()
    print(f"created {source_dir}")

    req = Requirement(dist_name)
    actual = finders.find_source_dir(tmp_context, work_dir, req, version_string)
    assert str(source_dir) == str(actual)


def test_pypi_cache_provider() -> None:
    url = "https://cache.test/simple/"

    # defaults: wheels only, hardcoded attributes
    provider = finders.PyPICacheProvider(cache_server_url=url)
    assert provider.sdist_server_url == url
    assert provider.include_sdists is False
    assert provider.include_wheels is True
    assert provider.ignore_platform is False
    assert provider.override_download_url is None
    assert provider.cooldown is None
    assert provider.supports_upload_time is False

    # sdists only with req_type
    provider = finders.PyPICacheProvider(
        cache_server_url=url,
        include_sdists=True,
        include_wheels=False,
        req_type=RequirementType.TOP_LEVEL,
    )
    assert provider.include_sdists is True
    assert provider.include_wheels is False
    assert provider.req_type == RequirementType.TOP_LEVEL

    # mutually exclusive: both True or both False
    with pytest.raises(ValueError, match="mutually exclusive"):
        finders.PyPICacheProvider(
            cache_server_url=url, include_sdists=True, include_wheels=True
        )
    with pytest.raises(ValueError, match="mutually exclusive"):
        finders.PyPICacheProvider(
            cache_server_url=url, include_sdists=False, include_wheels=False
        )


# -- LocalIndexProvider ------------------------------------------------------


def _create_local_file(directory: pathlib.Path, filename: str) -> pathlib.Path:
    """Create an empty file in the given directory."""
    path = directory / filename
    path.touch()
    return path


def test_local_init(tmp_path: pathlib.Path) -> None:
    provider = finders.LocalIndexProvider(path=tmp_path, flat=True)
    assert provider.path == tmp_path
    assert provider.flat is True
    assert provider.include_sdists is True
    assert provider.include_wheels is True
    assert provider.supports_upload_time is False
    assert provider.use_cache_candidates is False
    assert provider.cooldown is None

    with pytest.raises(NotImplementedError):
        _ = provider.cache_key

    desc = provider.get_provider_description()
    assert "Local" in desc
    assert str(tmp_path) in desc


def test_local_find_candidates_flat(tmp_path: pathlib.Path) -> None:
    """Flat mode finds wheels, sdists, and build-tagged wheels in one directory."""
    # wheel and sdist with same version
    _create_local_file(tmp_path, "example_pkg-1.0.0-py3-none-any.whl")
    _create_local_file(tmp_path, "example_pkg-1.0.0.tar.gz")
    # sdist filenames can use non-normalized names (dash, underscore, dot)
    _create_local_file(tmp_path, "example-pkg-2.0.0.tar.gz")
    _create_local_file(tmp_path, "example.pkg-3.0.0.tar.gz")
    _create_local_file(tmp_path, "example_pkg-4.0.0-2-py3-none-any.whl")
    # noise: other package, directory shaped like a wheel, non-dist file, invalid sdist
    _create_local_file(tmp_path, "other_pkg-1.0.0-py3-none-any.whl")
    tmp_path.joinpath("example_pkg-9.0.0-py3-none-any.whl").mkdir()
    _create_local_file(tmp_path, "README.md")
    _create_local_file(tmp_path, "not-a-valid-sdist.tar.gz")

    provider = finders.LocalIndexProvider(path=tmp_path, flat=True)
    candidates = list(provider.find_candidates("example-pkg"))

    # find_candidates filters by normalized name; other_pkg is excluded
    assert len(candidates) == 5
    assert all(c.name == "example-pkg" for c in candidates)

    # version 1.0.0 has both a wheel and an sdist
    v1 = [c for c in candidates if c.version == Version("1.0.0")]
    assert len(v1) == 2
    assert {c.is_sdist for c in v1} == {True, False}
    whl = next(c for c in v1 if not c.is_sdist)
    assert whl.upload_time is None
    assert whl.has_metadata is False

    # all sdist name variants normalize to example-pkg
    sdists = [c for c in candidates if c.is_sdist]
    assert {str(c.version) for c in sdists} == {"1.0.0", "2.0.0", "3.0.0"}

    assert next(c for c in candidates if c.version == Version("4.0.0")).build_tag == (
        2,
        "",
    )


def test_local_find_candidates_nested(tmp_path: pathlib.Path) -> None:
    """Nested mode looks up a subdirectory using the canonicalized name."""
    pkg_dir = tmp_path / "my-package"
    pkg_dir.mkdir()
    _create_local_file(pkg_dir, "my_package-1.0.0-py3-none-any.whl")

    provider = finders.LocalIndexProvider(path=tmp_path, flat=False)

    # Various spellings should all resolve via canonicalize_name
    for name in ("My_Package", "my.package", "MY-PACKAGE", "my-package"):
        candidates = list(provider.find_candidates(name))
        assert len(candidates) == 1, f"failed for {name!r}"
        assert candidates[0].name == "my-package"
        assert candidates[0].version == Version("1.0.0")

    # missing subdirectory returns no candidates
    assert list(provider.find_candidates("no-such-pkg")) == []


def test_local_find_candidates_include_flags(tmp_path: pathlib.Path) -> None:
    """include_sdists=False / include_wheels=False filters correctly."""
    _create_local_file(tmp_path, "example_pkg-1.0.0.tar.gz")
    _create_local_file(tmp_path, "example_pkg-1.0.0-py3-none-any.whl")

    wheels_only = finders.LocalIndexProvider(
        path=tmp_path, flat=True, include_sdists=False
    )
    assert all(not c.is_sdist for c in wheels_only.find_candidates("example-pkg"))

    sdists_only = finders.LocalIndexProvider(
        path=tmp_path, flat=True, include_wheels=False
    )
    assert all(c.is_sdist for c in sdists_only.find_candidates("example-pkg"))


def test_local_find_candidates_empty_dir(tmp_path: pathlib.Path) -> None:
    provider = finders.LocalIndexProvider(path=tmp_path, flat=True)
    assert list(provider.find_candidates("nonexistent-pkg")) == []


def test_local_find_matches(tmp_path: pathlib.Path) -> None:
    """find_matches sorts by version descending and respects constraints."""
    _create_local_file(tmp_path, "example_pkg-1.0.0-py3-none-any.whl")
    _create_local_file(tmp_path, "example_pkg-1.5.0-py3-none-any.whl")
    _create_local_file(tmp_path, "example_pkg-2.0.0-py3-none-any.whl")
    _create_local_file(tmp_path, "other_pkg-5.0.0-py3-none-any.whl")

    provider = finders.LocalIndexProvider(path=tmp_path, flat=True)
    req = Requirement("example-pkg")
    identifier = provider.identify(req)
    matches = list(
        provider.find_matches(
            identifier=identifier,
            requirements={identifier: [req]},
            incompatibilities={},
        )
    )
    # other_pkg is excluded by name; results sorted highest first
    assert [m.version for m in matches] == [
        Version("2.0.0"),
        Version("1.5.0"),
        Version("1.0.0"),
    ]

    # constraint filters out 2.0.0
    c = constraints.Constraints()
    c.add_constraint("example-pkg<2")
    provider_c = finders.LocalIndexProvider(path=tmp_path, flat=True, constraints=c)
    matches_c = list(
        provider_c.find_matches(
            identifier=identifier,
            requirements={identifier: [req]},
            incompatibilities={},
        )
    )
    assert [m.version for m in matches_c] == [Version("1.5.0"), Version("1.0.0")]

    # no match raises
    provider_miss = finders.LocalIndexProvider(path=tmp_path, flat=True)
    req_miss = Requirement("example-pkg>=5.0")
    with pytest.raises(resolvelib.resolvers.ResolverException):
        list(
            provider_miss.find_matches(
                identifier=identifier,
                requirements={identifier: [req_miss]},
                incompatibilities={},
            )
        )
