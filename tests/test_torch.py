import os.path
from unittest.mock import patch

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from mirror_builder.pkgs.overrides import torch


@patch('mirror_builder.sources.download_url')
@patch('mirror_builder.sources.resolve_sdist')
def test_torch_download_source_from_upstream(resolve_sdist, download_url, tmp_context):
    def mock_resolve_sdist(req, sdist_server_url, only_sdists=True):
        # Uses custom resolve_sdist() for sources from upstream
        assert not only_sdists
        resolutions = {
            'torch': '2.2.1',
        }
        return '', Version(resolutions[req.name])
    resolve_sdist.side_effect = mock_resolve_sdist

    def mock_download_url(destination_dir, url):
        assert url == 'https://github.com/pytorch/pytorch/releases/download/v2.2.1/pytorch-v2.2.1.tar.gz'
        return 'pytorch-v2.2.1.tar.gz'
    download_url.side_effect = mock_download_url

    req = Requirement('torch')
    sdist_server_url = 'https://pypi.org/simple'
    f, v = torch.download_source(tmp_context, req, sdist_server_url)

    assert str(v) == '2.2.1'
    assert os.path.basename(f) == 'pytorch-v2.2.1.tar.gz'


@pytest.mark.skip(reason="we always download from upstream, there is no cache, yet")
@patch('mirror_builder.sources.download_url')
@patch('mirror_builder.sources.resolve_sdist')
def test_torch_download_source_from_cache(resolve_sdist, download_url, tmp_context):
    def mock_resolve_sdist(req, sdist_server_url, only_sdists=True):
        assert sdist_server_url == 'not_upstream'
        # Uses regular resolve_sdist() for cached sources
        assert only_sdists
        resolutions = {
            'torch': '2.2.1',
        }
        return 'not_upstream_url', Version(resolutions[req.name])
    resolve_sdist.side_effect = mock_resolve_sdist

    def mock_download_url(destination_dir, url):
        assert url == 'not_upstream_url'
        return 'pytorch-v2.2.1.tar.gz'
    download_url.side_effect = mock_download_url

    req = Requirement('torch')
    sdist_server_url = 'not_upstream'
    f, v = torch.download_source(tmp_context, req, sdist_server_url)

    assert str(v) == '2.2.1'
    assert os.path.basename(f) == 'pytorch-v2.2.1.tar.gz'
