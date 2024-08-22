import pathlib

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import finders


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
def test_find_sdist(tmp_path, tmp_context, dist_name, version_string, expected_base):
    sdists_repo = pathlib.Path(tmp_path)
    downloads = sdists_repo / "downloads"
    downloads.mkdir()
    archive = downloads / expected_base
    archive.write_text("not-empty")

    req = Requirement(dist_name)
    ver = Version(version_string)
    actual = finders.find_sdist(tmp_context, downloads, req, ver)
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
def test_find_wheel(tmp_path, dist_name, version_string, expected_base):
    wheels_repo = pathlib.Path(tmp_path)
    downloads = wheels_repo / "downloads"
    downloads.mkdir()
    wheel = downloads / expected_base
    wheel.write_text("not-empty")

    req = Requirement(dist_name)
    ver = Version(version_string)
    actual = finders.find_wheel(downloads, req, ver, 0)
    assert str(wheel) == str(actual)


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
    tmp_path, tmp_context, dist_name, version_string, unpack_base, source_base
):
    work_dir = pathlib.Path(tmp_path)
    unpack_dir = work_dir / unpack_base
    unpack_dir.mkdir()
    source_dir = unpack_dir / source_base
    source_dir.mkdir()
    print(f"created {source_dir}")

    req = Requirement(dist_name)
    ver = Version(version_string)
    actual = finders.find_source_dir(tmp_context, work_dir, req, ver)
    assert str(source_dir) == str(actual)
