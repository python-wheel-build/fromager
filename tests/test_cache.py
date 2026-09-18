"""Unit tests for the fromager.cache module."""

import hashlib
import os
import pathlib
import re
import threading
import typing
from unittest.mock import MagicMock, patch

import pytest
import requests_mock
from click.testing import CliRunner
from packaging.requirements import Requirement
from packaging.tags import Tag
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager.cache import (
    ArtifactInfo,
    CacheManager,
    CacheStats,
    LocalDirectoryBackend,
    RemotePEP503Backend,
    WheelCacheKey,
    build_cache_manager,
)
from fromager.commands.cache_cmd import cache_cli

# ---------------------------------------------------------------------------
# WheelCacheKey
# ---------------------------------------------------------------------------


class TestWheelCacheKey:
    def test_str_with_build_tag(self) -> None:
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        assert str(key) == "requests==2.31.0-1"

    def test_str_without_build_tag(self) -> None:
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(),
        )
        assert str(key) == "requests==2.31.0"

    def test_equality(self) -> None:
        key1 = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        key2 = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        assert key1 == key2


# ---------------------------------------------------------------------------
# LocalDirectoryBackend
# ---------------------------------------------------------------------------


class TestLocalDirectoryBackend:
    def test_scan_empty_directory(self, tmp_path: pathlib.Path) -> None:
        backend = LocalDirectoryBackend(tmp_path, backend_name="test")
        result = backend.scan()
        assert result == {}

    def test_scan_nonexistent_directory(self, tmp_path: pathlib.Path) -> None:
        backend = LocalDirectoryBackend(tmp_path / "nonexistent", backend_name="test")
        result = backend.scan()
        assert result == {}

    def test_scan_finds_wheels(self, tmp_path: pathlib.Path) -> None:
        whl = tmp_path / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"fake wheel data")
        backend = LocalDirectoryBackend(tmp_path, backend_name="test")
        result = backend.scan()
        assert len(result) == 1
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        assert key in result

    def test_scan_skips_symlinks(self, tmp_path: pathlib.Path) -> None:
        real = tmp_path / "real" / "requests-2.31.0-1-py3-none-any.whl"
        real.parent.mkdir()
        real.write_bytes(b"fake")
        link = tmp_path / "requests-2.31.0-1-py3-none-any.whl"
        link.symlink_to(real)
        backend = LocalDirectoryBackend(tmp_path, backend_name="test")
        result = backend.scan()
        assert len(result) == 0

    def test_scan_skips_invalid_filenames(self, tmp_path: pathlib.Path) -> None:
        bad = tmp_path / "not_a_valid_wheel.whl"
        bad.write_bytes(b"bad")
        backend = LocalDirectoryBackend(tmp_path, backend_name="test")
        result = backend.scan()
        assert result == {}

    def test_lookup_found(self, tmp_path: pathlib.Path) -> None:
        whl = tmp_path / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"data")
        backend = LocalDirectoryBackend(tmp_path, backend_name="test")
        backend.scan()
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        info = backend.lookup(key)
        assert info is not None
        assert info.filename == "requests-2.31.0-1-py3-none-any.whl"

    def test_lookup_not_found(self, tmp_path: pathlib.Path) -> None:
        backend = LocalDirectoryBackend(tmp_path, backend_name="test")
        backend.scan()
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        assert backend.lookup(key) is None

    def test_lookup_evicts_deleted_file(self, tmp_path: pathlib.Path) -> None:
        whl = tmp_path / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"data")
        backend = LocalDirectoryBackend(tmp_path, backend_name="test")
        backend.scan()
        whl.unlink()
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        assert backend.lookup(key) is None

    def test_store_copies_file(self, tmp_path: pathlib.Path) -> None:
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        whl = source_dir / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"wheel content")

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        backend = LocalDirectoryBackend(dest_dir, backend_name="test")

        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        info = backend.store(key, whl)

        # Original still exists
        assert whl.exists()
        # Stored in dest
        stored = dest_dir / whl.name
        assert stored.exists()
        assert stored.read_bytes() == b"wheel content"
        assert info.filename == whl.name

    def test_store_same_file_noop(self, tmp_path: pathlib.Path) -> None:
        whl = tmp_path / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"data")
        backend = LocalDirectoryBackend(tmp_path, backend_name="test")
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        info = backend.store(key, whl)
        assert info.filename == whl.name

    def test_store_overwrites_stale_same_named_wheel(
        self, tmp_path: pathlib.Path
    ) -> None:
        """store() replaces an existing same-named wheel that is a different file."""
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        stale = dest_dir / "requests-2.31.0-1-py3-none-any.whl"
        stale.write_bytes(b"stale content")

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        fresh = source_dir / "requests-2.31.0-1-py3-none-any.whl"
        fresh.write_bytes(b"fresh content")

        backend = LocalDirectoryBackend(dest_dir, backend_name="test")
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        info = backend.store(key, fresh)

        assert stale.read_bytes() == b"fresh content"
        assert info.size_bytes == len(b"fresh content")
        assert backend.lookup(key) is not None

    def test_fetch_returns_local_path(self, tmp_path: pathlib.Path) -> None:
        whl = tmp_path / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"data")
        backend = LocalDirectoryBackend(tmp_path, backend_name="test")
        backend.scan()
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        info = backend.lookup(key)
        assert info is not None
        path = backend.fetch(key, info, tmp_path / "other")
        assert path == pathlib.Path(info.url_or_path)

    def test_items_returns_all(self, tmp_path: pathlib.Path) -> None:
        whl1 = tmp_path / "requests-2.31.0-1-py3-none-any.whl"
        whl1.write_bytes(b"a")
        whl2 = tmp_path / "urllib3-2.0.0-1-py3-none-any.whl"
        whl2.write_bytes(b"b")
        backend = LocalDirectoryBackend(tmp_path, backend_name="test")
        backend.scan()
        items = list(backend.items())
        assert len(items) == 2

    def test_scan_skips_incompatible_platform_wheels(
        self, tmp_path: pathlib.Path
    ) -> None:
        compatible = tmp_path / "requests-2.31.0-1-py3-none-any.whl"
        incompatible = tmp_path / "requests-2.31.0-1-cp39-cp39-win_amd64.whl"
        compatible.write_bytes(b"ok")
        incompatible.write_bytes(b"nope")
        backend = LocalDirectoryBackend(tmp_path, backend_name="test")
        with patch(
            "fromager.cache.SUPPORTED_TAGS",
            frozenset({Tag("py3", "none", "any")}),
        ):
            backend.scan()
            key = WheelCacheKey(
                package=canonicalize_name("requests"),
                version=Version("2.31.0"),
                build_tag=(1, ""),
            )
            info = backend.lookup(key)
        assert info is not None
        assert info.filename == compatible.name

    def test_scan_recursive_finds_thread_subdir_wheels(
        self, tmp_path: pathlib.Path
    ) -> None:
        nested = tmp_path / "12345"
        nested.mkdir()
        whl = nested / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"data")
        backend = LocalDirectoryBackend(
            tmp_path, backend_name="local:build", recursive=True
        )
        backend.scan()
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        assert backend.lookup(key) is not None


# ---------------------------------------------------------------------------
# RemotePEP503Backend
# ---------------------------------------------------------------------------


class TestRemotePEP503Backend:
    def test_parse_index_page(self) -> None:
        html = """
        <html><body>
        <a href="requests/">requests</a>
        <a href="urllib3/">urllib3</a>
        </body></html>
        """
        names = RemotePEP503Backend._parse_index_page(html)
        assert canonicalize_name("requests") in names
        assert canonicalize_name("urllib3") in names

    def test_parse_index_page_allows_extra_attributes(self) -> None:
        html = """
        <a data-requires-python=">=3.8" href="requests/">requests</a>
        """
        names = RemotePEP503Backend._parse_index_page(html)
        assert canonicalize_name("requests") in names

    def test_parse_project_page(self) -> None:
        html = """
        <a href="requests-2.31.0-1-py3-none-any.whl#sha256=abc123">requests-2.31.0-1-py3-none-any.whl</a>
        <a href="requests-2.31.0.tar.gz#sha256=def456">requests-2.31.0.tar.gz</a>
        """
        artifacts = RemotePEP503Backend._parse_project_page(
            html, "https://cache.test/simple/requests/"
        )
        assert len(artifacts) == 1
        assert artifacts[0].filename == "requests-2.31.0-1-py3-none-any.whl"
        assert artifacts[0].sha256 == "abc123"

    def test_parse_project_page_rejects_path_traversal(self) -> None:
        # Link text must end in .whl to pass the suffix check and reach the
        # safe_filename != filename traversal guard.
        html = """
        <a href="../../../evil-1.0.0-py3-none-any.whl">../../../evil-1.0.0-py3-none-any.whl</a>
        <a href="requests-2.31.0-1-py3-none-any.whl#sha256=abc">requests-2.31.0-1-py3-none-any.whl</a>
        """
        artifacts = RemotePEP503Backend._parse_project_page(
            html, "https://cache.test/simple/requests/"
        )
        assert len(artifacts) == 1
        assert artifacts[0].filename == "requests-2.31.0-1-py3-none-any.whl"

    def test_parse_project_page_rejects_http_without_sha256(self) -> None:
        html = """
        <a href="http://cache.test/requests-2.31.0-1-py3-none-any.whl">requests-2.31.0-1-py3-none-any.whl</a>
        """
        artifacts = RemotePEP503Backend._parse_project_page(
            html, "http://cache.test/simple/requests/"
        )
        assert len(artifacts) == 0

    def test_parse_project_page_allows_http_with_sha256(self) -> None:
        html = """
        <a href="http://cache.test/requests-2.31.0-1-py3-none-any.whl#sha256=abc123">requests-2.31.0-1-py3-none-any.whl</a>
        """
        artifacts = RemotePEP503Backend._parse_project_page(
            html, "http://cache.test/simple/requests/"
        )
        assert len(artifacts) == 1

    def test_parse_project_page_resolves_uppercase_absolute_scheme(self) -> None:
        """Absolute href schemes are case-insensitive (RFC 3986)."""
        html = """
        <a href="HTTPS://CACHE.TEST/requests-2.31.0-1-py3-none-any.whl#sha256=abc">requests-2.31.0-1-py3-none-any.whl</a>
        """
        artifacts = RemotePEP503Backend._parse_project_page(
            html, "https://cache.test/simple/requests/"
        )
        assert len(artifacts) == 1
        assert artifacts[0].url_or_path.startswith("HTTPS://CACHE.TEST/")

    def test_parse_project_page_allows_http_insecure(self) -> None:
        html = """
        <a href="http://cache.test/requests-2.31.0-1-py3-none-any.whl">requests-2.31.0-1-py3-none-any.whl</a>
        """
        artifacts = RemotePEP503Backend._parse_project_page(
            html, "http://cache.test/simple/requests/", allow_insecure=True
        )
        assert len(artifacts) == 1

    def test_scan_fetches_package_list(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        requests_mock.get(
            "https://cache.test/simple/",
            text='<a href="requests/">requests</a>',
        )
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        backend.scan()
        assert backend._available_packages is not None
        assert canonicalize_name("requests") in backend._available_packages

    def test_lookup_fetches_project_page(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        requests_mock.get(
            "https://cache.test/simple/",
            text='<a href="requests/">requests</a>',
        )
        requests_mock.get(
            "https://cache.test/simple/requests/",
            text='<a href="requests-2.31.0-1-py3-none-any.whl#sha256=abc">requests-2.31.0-1-py3-none-any.whl</a>',
        )
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        backend.scan()
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        info = backend.lookup(key)
        assert info is not None
        assert info.sha256 == "abc"

    def test_lookup_short_circuits_unknown_package(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        requests_mock.get(
            "https://cache.test/simple/",
            text='<a href="requests/">requests</a>',
        )
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        backend.scan()
        key = WheelCacheKey(
            package=canonicalize_name("nonexistent"),
            version=Version("1.0.0"),
            build_tag=(),
        )
        assert backend.lookup(key) is None

    def test_scan_index_failure_still_allows_project_lookup(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        requests_mock.get("https://cache.test/simple/", status_code=500)
        requests_mock.get(
            "https://cache.test/simple/requests/",
            text='<a href="requests-2.31.0-1-py3-none-any.whl#sha256=abc">requests-2.31.0-1-py3-none-any.whl</a>',
        )
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        backend.scan()
        assert backend._available_packages is None
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        assert backend.lookup(key) is not None

    def test_project_page_5xx_is_not_memoized(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        requests_mock.get(
            "https://cache.test/simple/",
            text='<a href="requests/">requests</a>',
        )
        project_mock = requests_mock.get(
            "https://cache.test/simple/requests/",
            [
                {"status_code": 500},
                {
                    "text": (
                        '<a href="requests-2.31.0-1-py3-none-any.whl#sha256=abc">'
                        "requests-2.31.0-1-py3-none-any.whl</a>"
                    )
                },
            ],
        )
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        backend.scan()
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        assert backend.lookup(key) is None
        assert backend.lookup(key) is not None
        assert project_mock.call_count == 2

    def test_project_page_404_is_memoized_empty(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        requests_mock.get(
            "https://cache.test/simple/",
            text='<a href="requests/">requests</a>',
        )
        project_mock = requests_mock.get(
            "https://cache.test/simple/requests/",
            status_code=404,
        )
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        backend.scan()
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        assert backend.lookup(key) is None
        assert backend.lookup(key) is None
        assert project_mock.call_count == 1

    def test_scan_index_400_treated_as_empty(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        requests_mock.get("https://cache.test/simple/", status_code=400)
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        backend.scan()
        assert backend._available_packages == set()

    def test_parse_project_page_skips_yanked(self) -> None:
        html = """
        <a href="requests-2.31.0-1-py3-none-any.whl#sha256=bad"
           data-yanked="broken">requests-2.31.0-1-py3-none-any.whl</a>
        <a href="requests-2.32.0-1-py3-none-any.whl#sha256=good">requests-2.32.0-1-py3-none-any.whl</a>
        """
        artifacts = RemotePEP503Backend._parse_project_page(
            html, "https://cache.test/simple/requests/"
        )
        assert len(artifacts) == 1
        assert artifacts[0].filename == "requests-2.32.0-1-py3-none-any.whl"

    def test_parse_project_page_skips_incompatible_requires_python(self) -> None:
        html = """
        <a href="requests-2.31.0-1-py3-none-any.whl#sha256=old"
           data-requires-python=">=99">requests-2.31.0-1-py3-none-any.whl</a>
        <a href="requests-2.32.0-1-py3-none-any.whl#sha256=ok"
           data-requires-python=">=3.8">requests-2.32.0-1-py3-none-any.whl</a>
        """
        artifacts = RemotePEP503Backend._parse_project_page(
            html, "https://cache.test/simple/requests/"
        )
        assert len(artifacts) == 1
        assert artifacts[0].filename == "requests-2.32.0-1-py3-none-any.whl"

    def test_parse_project_page_unescapes_requires_python_entities(self) -> None:
        """Warehouse emits HTML-escaped requires-python (e.g. &gt;=3.8)."""
        html = """
        <a href="requests-2.32.0-1-py3-none-any.whl#sha256=ok"
           data-requires-python="&gt;=3.8">requests-2.32.0-1-py3-none-any.whl</a>
        """
        artifacts = RemotePEP503Backend._parse_project_page(
            html, "https://cache.test/simple/requests/"
        )
        assert len(artifacts) == 1
        assert artifacts[0].filename == "requests-2.32.0-1-py3-none-any.whl"

    def test_parse_project_page_unquotes_percent_encoded_filenames(self) -> None:
        """Local versions use '+' which simple indexes percent-encode as %2B."""
        html = """
        <a href="torch-2.0.0%2Bcpu-py3-none-any.whl#sha256=abc">torch-2.0.0%2Bcpu-py3-none-any.whl</a>
        """
        artifacts = RemotePEP503Backend._parse_project_page(
            html, "https://cache.test/simple/torch/"
        )
        assert len(artifacts) == 1
        assert artifacts[0].filename == "torch-2.0.0+cpu-py3-none-any.whl"

    def test_lookup_accepts_percent_encoded_local_version(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        requests_mock.get(
            "https://cache.test/simple/",
            text='<a href="torch/">torch</a>',
        )
        requests_mock.get(
            "https://cache.test/simple/torch/",
            text=(
                '<a href="torch-2.0.0%2Bcpu-py3-none-any.whl#sha256=abc">'
                "torch-2.0.0%2Bcpu-py3-none-any.whl</a>"
            ),
        )
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        backend.scan()
        key = WheelCacheKey(
            package=canonicalize_name("torch"),
            version=Version("2.0.0+cpu"),
            build_tag=(),
        )
        info = backend.lookup(key)
        assert info is not None
        assert info.filename == "torch-2.0.0+cpu-py3-none-any.whl"

    def test_lookup_skips_incompatible_platform_wheels(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        requests_mock.get(
            "https://cache.test/simple/",
            text='<a href="requests/">requests</a>',
        )
        requests_mock.get(
            "https://cache.test/simple/requests/",
            text=(
                '<a href="requests-2.31.0-1-cp39-cp39-win_amd64.whl#sha256=bad">'
                "requests-2.31.0-1-cp39-cp39-win_amd64.whl</a>"
                '<a href="requests-2.31.0-1-py3-none-any.whl#sha256=good">'
                "requests-2.31.0-1-py3-none-any.whl</a>"
            ),
        )
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        backend.scan()
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        with patch(
            "fromager.cache.SUPPORTED_TAGS",
            frozenset({Tag("py3", "none", "any")}),
        ):
            info = backend.lookup(key)
        assert info is not None
        assert info.filename == "requests-2.31.0-1-py3-none-any.whl"
        assert info.sha256 == "good"

    def test_fetch_downloads_wheel(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        wheel_data = b"fake wheel content"
        sha256 = hashlib.sha256(wheel_data).hexdigest()
        requests_mock.get(
            "https://cache.test/simple/requests/requests-2.31.0-1-py3-none-any.whl",
            content=wheel_data,
        )
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        info = ArtifactInfo(
            filename="requests-2.31.0-1-py3-none-any.whl",
            url_or_path="https://cache.test/simple/requests/requests-2.31.0-1-py3-none-any.whl",
            sha256=sha256,
        )
        dest = tmp_path / "downloads"
        dest.mkdir()
        result = backend.fetch(key, info, dest)
        assert result.exists()
        assert result.read_bytes() == wheel_data

    def test_fetch_rejects_sha256_mismatch(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        requests_mock.get(
            "https://cache.test/simple/requests/requests-2.31.0-1-py3-none-any.whl",
            content=b"corrupted content",
        )
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        info = ArtifactInfo(
            filename="requests-2.31.0-1-py3-none-any.whl",
            url_or_path="https://cache.test/simple/requests/requests-2.31.0-1-py3-none-any.whl",
            sha256="expected_sha256_that_wont_match",
        )
        dest = tmp_path / "downloads"
        dest.mkdir()
        with pytest.raises(ValueError, match="sha256 mismatch"):
            backend.fetch(key, info, dest)

    def test_fetch_uses_cached_file_if_sha256_matches(
        self, tmp_path: pathlib.Path
    ) -> None:
        wheel_data = b"cached wheel"
        sha256 = hashlib.sha256(wheel_data).hexdigest()
        dest = tmp_path / "downloads"
        dest.mkdir()
        existing = dest / "requests-2.31.0-1-py3-none-any.whl"
        existing.write_bytes(wheel_data)

        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        info = ArtifactInfo(
            filename="requests-2.31.0-1-py3-none-any.whl",
            url_or_path="https://cache.test/simple/requests/requests-2.31.0-1-py3-none-any.whl",
            sha256=sha256,
        )
        result = backend.fetch(key, info, dest)
        assert result == existing

    def test_fetch_accepts_uppercase_sha256(self, tmp_path: pathlib.Path) -> None:
        """Index fragments may advertise uppercase hex digests."""
        wheel_data = b"cached wheel"
        sha256 = hashlib.sha256(wheel_data).hexdigest().upper()
        dest = tmp_path / "downloads"
        dest.mkdir()
        existing = dest / "requests-2.31.0-1-py3-none-any.whl"
        existing.write_bytes(wheel_data)

        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        info = ArtifactInfo(
            filename="requests-2.31.0-1-py3-none-any.whl",
            url_or_path="https://cache.test/simple/requests/requests-2.31.0-1-py3-none-any.whl",
            sha256=sha256,
        )
        result = backend.fetch(key, info, dest)
        assert result == existing

    def test_fetch_redownloads_when_existing_sha256_mismatches(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        wheel_data = b"good wheel"
        sha256 = hashlib.sha256(wheel_data).hexdigest()
        url = "https://cache.test/simple/requests/requests-2.31.0-1-py3-none-any.whl"
        requests_mock.get(url, content=wheel_data)
        dest = tmp_path / "downloads"
        dest.mkdir()
        existing = dest / "requests-2.31.0-1-py3-none-any.whl"
        existing.write_bytes(b"stale")

        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        info = ArtifactInfo(
            filename="requests-2.31.0-1-py3-none-any.whl",
            url_or_path=url,
            sha256=sha256,
        )
        result = backend.fetch(key, info, dest)
        assert result.read_bytes() == wheel_data

    def test_store_raises(self, tmp_path: pathlib.Path) -> None:
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path,
        )
        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        with pytest.raises(NotImplementedError):
            backend.store(key, tmp_path / "fake.whl")


# ---------------------------------------------------------------------------
# CacheManager
# ---------------------------------------------------------------------------


class TestCacheManager:
    def _make_manager(
        self, tmp_path: pathlib.Path
    ) -> tuple[CacheManager, LocalDirectoryBackend]:
        store = LocalDirectoryBackend(tmp_path / "downloads", backend_name="store")
        build = LocalDirectoryBackend(tmp_path / "build", backend_name="build")
        manager = CacheManager(
            lookup_backends=[build, store],
            store_backend=store,
        )
        return manager, store

    def test_lookup_miss(self, tmp_path: pathlib.Path) -> None:
        manager, _ = self._make_manager(tmp_path)
        (tmp_path / "downloads").mkdir()
        (tmp_path / "build").mkdir()
        manager.initialize()
        result = manager.lookup_wheel(
            Requirement("requests"), Version("2.31.0"), (1, "")
        )
        assert result.miss

    def test_lookup_hit_in_store(self, tmp_path: pathlib.Path) -> None:
        downloads = tmp_path / "downloads"
        downloads.mkdir()
        whl = downloads / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"data")
        (tmp_path / "build").mkdir()

        manager, _ = self._make_manager(tmp_path)
        manager.initialize()
        result = manager.lookup_wheel(
            Requirement("requests"), Version("2.31.0"), (1, "")
        )
        assert result.hit
        assert result.was_downloaded is False
        assert result.path == whl.resolve()

    def test_lookup_empty_build_tag_matches_tagged_wheel(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Empty expected build tag matches wheels with tag 0 (legacy semantics)."""
        downloads = tmp_path / "downloads"
        downloads.mkdir()
        whl = downloads / "requests-2.31.0-0-py3-none-any.whl"
        whl.write_bytes(b"data")
        (tmp_path / "build").mkdir()

        manager, _ = self._make_manager(tmp_path)
        manager.initialize()
        result = manager.lookup_wheel(Requirement("requests"), Version("2.31.0"), ())
        assert result.hit
        assert result.path == whl.resolve()
        assert result.build_tag == (0, "")

    def test_lookup_hit_in_build_copies_to_store(self, tmp_path: pathlib.Path) -> None:
        downloads = tmp_path / "downloads"
        downloads.mkdir()
        build = tmp_path / "build"
        build.mkdir()
        whl = build / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"build data")

        manager, _store = self._make_manager(tmp_path)
        manager.initialize()
        result = manager.lookup_wheel(
            Requirement("requests"), Version("2.31.0"), (1, "")
        )
        assert result.hit
        assert result.was_downloaded is True
        stored = downloads / "requests-2.31.0-1-py3-none-any.whl"
        assert stored.exists()
        # Promoted hits expose the store path, not the build-dir source.
        assert result.path == stored.resolve()

    def test_lookup_forced_miss(self, tmp_path: pathlib.Path) -> None:
        downloads = tmp_path / "downloads"
        downloads.mkdir()
        whl = downloads / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"data")
        (tmp_path / "build").mkdir()

        store = LocalDirectoryBackend(downloads, backend_name="store")
        manager = CacheManager(
            lookup_backends=[store],
            store_backend=store,
            force=True,
        )
        manager.initialize()
        result = manager.lookup_wheel(
            Requirement("requests"), Version("2.31.0"), (1, "")
        )
        assert result.miss

    def test_store_wheel(self, tmp_path: pathlib.Path) -> None:
        downloads = tmp_path / "downloads"
        downloads.mkdir()
        (tmp_path / "build").mkdir()

        source = tmp_path / "built" / "requests-2.31.0-1-py3-none-any.whl"
        source.parent.mkdir()
        source.write_bytes(b"built wheel")

        manager, _ = self._make_manager(tmp_path)
        manager.initialize()
        stored_path = manager.store_wheel(
            Requirement("requests"), Version("2.31.0"), (1, ""), source
        )
        assert pathlib.Path(stored_path).exists()
        assert (downloads / source.name).exists()

    def test_stats_recording(self, tmp_path: pathlib.Path) -> None:
        downloads = tmp_path / "downloads"
        downloads.mkdir()
        whl = downloads / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"data")
        (tmp_path / "build").mkdir()

        manager, _ = self._make_manager(tmp_path)
        manager.initialize()

        manager.lookup_wheel(Requirement("requests"), Version("2.31.0"), (1, ""))
        manager.lookup_wheel(Requirement("nonexist"), Version("1.0.0"), ())

        assert manager.stats.hits == 1
        assert manager.stats.misses == 1

    def test_lookup_continues_on_fetch_failure(self, tmp_path: pathlib.Path) -> None:
        """If a backend's fetch() fails, lookup continues to next backend."""
        downloads = tmp_path / "downloads"
        downloads.mkdir()
        build = tmp_path / "build"
        build.mkdir()
        whl = build / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"fallback data")

        # Create a failing backend mock
        failing_backend = MagicMock()
        failing_backend.name = "failing"
        failing_backend.writable = True
        failing_backend.lookup.return_value = ArtifactInfo(
            filename="requests-2.31.0-1-py3-none-any.whl",
            url_or_path="/nonexistent",
        )
        failing_backend.fetch.side_effect = OSError("disk error")

        build_backend = LocalDirectoryBackend(build, backend_name="build")
        build_backend.scan()

        store = LocalDirectoryBackend(downloads, backend_name="store")
        manager = CacheManager(
            lookup_backends=[failing_backend, build_backend],
            store_backend=store,
        )
        result = manager.lookup_wheel(
            Requirement("requests"), Version("2.31.0"), (1, "")
        )
        assert result.hit
        assert result.path == (downloads / whl.name).resolve()


# ---------------------------------------------------------------------------
# CacheStats
# ---------------------------------------------------------------------------


class TestCacheStats:
    def test_hit_rate(self) -> None:
        stats = CacheStats()
        req = Requirement("requests")
        ver = Version("2.31.0")
        stats.record_hit(req, ver, "local")
        stats.record_miss(req, ver, "not_found")
        assert stats.hit_rate == 0.5

    def test_summary(self) -> None:
        stats = CacheStats()
        req = Requirement("requests")
        ver = Version("2.31.0")
        stats.record_hit(req, ver, "local:downloads")
        stats.record_store(req, ver, "local:downloads")
        summary = stats.summary()
        assert summary["hits"]["total"] == 1
        assert summary["stores"] == 1
        assert "local:downloads" in summary["hits"]["by_backend"]


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_store_and_lookup(self, tmp_path: pathlib.Path) -> None:
        """Multiple threads can safely contend on the same cache key."""
        backend = LocalDirectoryBackend(tmp_path, backend_name="test")
        errors: list[Exception] = []
        key = WheelCacheKey(
            package=canonicalize_name("pkg"),
            version=Version("1.0.0"),
            build_tag=(1, ""),
        )
        source_dir = tmp_path / "sources"
        source_dir.mkdir()

        def store_worker(idx: int) -> None:
            try:
                dest_name = "pkg-1.0.0-1-py3-none-any.whl"
                unique = source_dir / f"t{idx}" / dest_name
                unique.parent.mkdir()
                unique.write_bytes(f"data{idx}".encode())
                backend.store(key, unique)
            except Exception as e:
                errors.append(e)

        def lookup_worker() -> None:
            try:
                for _ in range(20):
                    backend.lookup(key)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=store_worker, args=(i,)) for i in range(10)]
        threads.extend(threading.Thread(target=lookup_worker) for _ in range(10))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        info = backend.lookup(key)
        assert info is not None
        assert pathlib.Path(info.url_or_path).exists()
        assert pathlib.Path(info.url_or_path).read_bytes().startswith(b"data")

    def test_concurrent_scan_and_lookup(self, tmp_path: pathlib.Path) -> None:
        """Scanning while lookups are happening doesn't crash."""
        for i in range(5):
            whl = tmp_path / f"pkg{i}-1.0.0-1-py3-none-any.whl"
            whl.write_bytes(f"data{i}".encode())

        backend = LocalDirectoryBackend(tmp_path, backend_name="test")
        backend.scan()
        errors: list[Exception] = []

        def scan_worker() -> None:
            try:
                backend.scan()
            except Exception as e:
                errors.append(e)

        def lookup_worker() -> None:
            try:
                for i in range(5):
                    key = WheelCacheKey(
                        package=canonicalize_name(f"pkg{i}"),
                        version=Version("1.0.0"),
                        build_tag=(1, ""),
                    )
                    backend.lookup(key)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=scan_worker),
            threading.Thread(target=lookup_worker),
            threading.Thread(target=lookup_worker),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ---------------------------------------------------------------------------
# CLI commands (via CliRunner)
# ---------------------------------------------------------------------------


class TestCLICommands:
    @pytest.fixture()
    def wkctx(self, tmp_path: pathlib.Path) -> typing.Any:
        """Minimal WorkContext-like object for CLI tests."""
        wkctx = MagicMock()
        wkctx.wheels_build_base = tmp_path / "build"
        wkctx.wheels_build_base.mkdir()
        wkctx.wheels_downloads = tmp_path / "downloads"
        wkctx.wheels_downloads.mkdir()
        wkctx.wheels_prebuilt = tmp_path / "prebuilt"
        wkctx.wheels_prebuilt.mkdir()
        wkctx.cache = None
        return wkctx

    def test_cache_list_empty(self, wkctx: typing.Any) -> None:
        runner = CliRunner()
        result = runner.invoke(cache_cli, ["list"], obj=wkctx)
        assert result.exit_code == 0
        assert "No cached wheels found" in result.output

    def test_cache_list_with_wheels(self, wkctx: typing.Any) -> None:
        whl = wkctx.wheels_downloads / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"fake")

        runner = CliRunner()
        result = runner.invoke(cache_cli, ["list", "--format", "json"], obj=wkctx)
        assert result.exit_code == 0
        assert "requests" in result.output

    def test_cache_stats(self, wkctx: typing.Any) -> None:
        whl = wkctx.wheels_downloads / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"data")

        runner = CliRunner()
        result = runner.invoke(cache_cli, ["stats"], obj=wkctx)
        assert result.exit_code == 0
        assert "Cache Inventory" in result.output
        assert "local:downloads wheels" in result.output
        # Rich table cells are padded; match the metric/value pair loosely.
        assert re.search(r"Total wheels on disk\s+1\b", result.output)

    def test_cache_gc_keeps_latest_by_mtime(self, wkctx: typing.Any) -> None:
        """Untagged wheels are ordered by mtime so --keep-latest keeps newest."""
        older = wkctx.wheels_downloads / "requests-2.31.0-py3-none-any.whl"
        newer = wkctx.wheels_downloads / "requests-2.31.0-0-py3-none-any.whl"
        older.write_bytes(b"older")
        newer.write_bytes(b"newer")
        # Force deterministic recency regardless of write order.
        older_mtime = 1_700_000_000
        newer_mtime = 1_700_000_100
        os.utime(older, (older_mtime, older_mtime))
        os.utime(newer, (newer_mtime, newer_mtime))

        runner = CliRunner()
        result = runner.invoke(cache_cli, ["gc", "--keep-latest", "1"], obj=wkctx)
        assert result.exit_code == 0
        assert newer.exists()
        assert not older.exists()

    def test_cache_verify_ok(self, wkctx: typing.Any) -> None:
        runner = CliRunner()
        result = runner.invoke(cache_cli, ["verify"], obj=wkctx)
        assert result.exit_code == 0
        assert "verified OK" in result.output

    def test_cache_gc_nothing_to_remove(self, wkctx: typing.Any) -> None:
        runner = CliRunner()
        result = runner.invoke(cache_cli, ["gc"], obj=wkctx)
        assert result.exit_code == 0
        assert "Removed 0" in result.output

    def test_cache_invalidate_requires_args(self, wkctx: typing.Any) -> None:
        runner = CliRunner()
        result = runner.invoke(cache_cli, ["invalidate"], obj=wkctx)
        assert result.exit_code != 0

    def test_cache_invalidate_all(self, wkctx: typing.Any) -> None:
        whl = wkctx.wheels_downloads / "requests-2.31.0-1-py3-none-any.whl"
        whl.write_bytes(b"data")

        runner = CliRunner()
        result = runner.invoke(cache_cli, ["invalidate", "--all"], obj=wkctx)
        assert result.exit_code == 0
        assert "Invalidated 1" in result.output
        assert not whl.exists()

    def test_cache_invalidate_preserves_prebuilt_and_build(
        self, wkctx: typing.Any
    ) -> None:
        """Destructive ops only touch the downloads store backend."""
        downloads_whl = wkctx.wheels_downloads / "requests-2.31.0-1-py3-none-any.whl"
        downloads_whl.write_bytes(b"downloads")
        prebuilt_whl = wkctx.wheels_prebuilt / "urllib3-2.0.0-1-py3-none-any.whl"
        prebuilt_whl.write_bytes(b"prebuilt")
        build_whl = wkctx.wheels_build_base / "idna-3.0-1-py3-none-any.whl"
        build_whl.write_bytes(b"build")

        runner = CliRunner()
        result = runner.invoke(cache_cli, ["invalidate", "--all"], obj=wkctx)
        assert result.exit_code == 0
        assert not downloads_whl.exists()
        assert prebuilt_whl.exists()
        assert build_whl.exists()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestBuildCacheManager:
    def test_lookup_order_includes_build_dir(self, tmp_path: pathlib.Path) -> None:
        """Factory searches build then downloads; prebuilt is intentionally omitted."""
        wkctx = MagicMock()
        wkctx.wheels_build_base = tmp_path / "build"
        wkctx.wheels_build_base.mkdir()
        wkctx.wheels_downloads = tmp_path / "downloads"
        wkctx.wheels_downloads.mkdir()
        wkctx.wheels_prebuilt = tmp_path / "prebuilt"
        wkctx.wheels_prebuilt.mkdir()
        wkctx.cache = None

        manager = build_cache_manager(wkctx)
        names = [b.name for b in manager.lookup_backends]
        assert names == ["local:build", "local:downloads"]
        assert manager.store_backend.name == "local:downloads"
        assert wkctx.cache is manager
        assert build_cache_manager(wkctx) is manager
        build_backend = manager.lookup_backends[0]
        assert isinstance(build_backend, LocalDirectoryBackend)
        assert build_backend._recursive is True

    def test_returns_existing_cache(self, tmp_path: pathlib.Path) -> None:
        existing = MagicMock()
        wkctx = MagicMock()
        wkctx.cache = existing
        assert build_cache_manager(wkctx) is existing

    def test_adds_remote_backend_with_allow_insecure(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        wkctx = MagicMock()
        wkctx.wheels_build_base = tmp_path / "build"
        wkctx.wheels_build_base.mkdir()
        wkctx.wheels_downloads = tmp_path / "downloads"
        wkctx.wheels_downloads.mkdir()
        wkctx.wheels_prebuilt = tmp_path / "prebuilt"
        wkctx.wheels_prebuilt.mkdir()
        wkctx.cache = None

        cache_url = "https://cache.test/simple"
        requests_mock.get(
            f"{cache_url}/",
            text='<html><body><a href="requests/">requests</a></body></html>',
        )
        manager = build_cache_manager(wkctx, cache_url=cache_url, allow_insecure=True)
        names = [b.name for b in manager.lookup_backends]
        assert names == [
            "local:build",
            "local:downloads",
            f"remote:{cache_url}",
        ]
        assert isinstance(manager.lookup_backends[-1], RemotePEP503Backend)
