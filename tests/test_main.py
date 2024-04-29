import pathlib

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from mirror_builder import __main__ as main


@pytest.mark.parametrize('dist_name,version_string,expected_base', [
    ('mypkg', '1.2', 'mypkg-1.2.tar.gz'),
    ('torch', '2.0', 'pytorch-v2.0.tar.gz'),
    ('oslo.messaging', '14.7.0', 'oslo.messaging-14.7.0.tar.gz'),
    ('cython', '3.0.10', 'Cython-3.0.10.tar.gz'),
])
def test_find_sdist(tmp_path, dist_name, version_string, expected_base):
    sdists_repo = pathlib.Path(tmp_path)
    downloads = sdists_repo / 'downloads'
    downloads.mkdir()
    archive = downloads / expected_base
    archive.write_text('not-empty')

    req = Requirement(dist_name)
    ver = Version(version_string)
    actual = main._find_sdist(sdists_repo, req, ver)
    assert str(archive) == str(actual)


@pytest.mark.parametrize('dist_name,version_string,expected_base', [
    ('mypkg', '1.2', 'mypkg-1.2'),
    ('torch', '2.0', 'pytorch-v2.0'),
    ('oslo.messaging', '14.7.0', 'oslo.messaging-14.7.0'),
    ('cython', '3.0.10', 'Cython-3.0.10'),
])
def test_find_source_dir(tmp_path, dist_name, version_string, expected_base):
    work_dir = pathlib.Path(tmp_path)
    unpack_dir = work_dir / expected_base
    unpack_dir.mkdir()
    source_dir = unpack_dir / expected_base
    source_dir.mkdir()

    req = Requirement(dist_name)
    ver = Version(version_string)
    actual = main._find_source_dir(work_dir, req, ver)
    assert str(source_dir) == str(actual)
