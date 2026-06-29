"""Unit tests for the cache subsystem."""

import pathlib

import pytest
import requests_mock
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager.cache import (
    CacheCollection,
    CacheManager,
    CacheResult,
    CacheStats,
    LocalDirectoryBackend,
    RemotePEP503Backend,
    SdistCacheKey,
    StoreRouter,
    WheelCacheKey,
)

# ---------------------------------------------------------------------------
# WheelCacheKey tests
# ---------------------------------------------------------------------------


class TestWheelCacheKey:
    def test_creation(self) -> None:
        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        assert key.package == "numpy"
        assert key.version == Version("1.26.4")
        assert key.build_tag == (2, "")

    def test_equality(self) -> None:
        key1 = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        key2 = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        assert key1 == key2

    def test_inequality_version(self) -> None:
        key1 = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        key2 = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.5"),
            build_tag=(2, ""),
        )
        assert key1 != key2

    def test_inequality_build_tag(self) -> None:
        key1 = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        key2 = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(3, ""),
        )
        assert key1 != key2

    def test_hashable(self) -> None:
        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        d: dict[WheelCacheKey, str] = {key: "found"}
        assert d[key] == "found"

    def test_str_with_build_tag(self) -> None:
        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        assert str(key) == "numpy==1.26.4-2"

    def test_str_without_build_tag(self) -> None:
        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(),
        )
        assert str(key) == "numpy==1.26.4"

    def test_name_normalization(self) -> None:
        key1 = WheelCacheKey(
            package=canonicalize_name("Flask-RESTful"),
            version=Version("0.3.10"),
            build_tag=(),
        )
        key2 = WheelCacheKey(
            package=canonicalize_name("flask_restful"),
            version=Version("0.3.10"),
            build_tag=(),
        )
        assert key1 == key2


class TestSdistCacheKey:
    def test_creation(self) -> None:
        key = SdistCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
        )
        assert key.package == "requests"
        assert str(key) == "requests==2.31.0"


# ---------------------------------------------------------------------------
# LocalDirectoryBackend tests
# ---------------------------------------------------------------------------


def _create_wheel_file(directory: pathlib.Path, filename: str) -> pathlib.Path:
    """Create a fake wheel file for testing."""
    directory.mkdir(parents=True, exist_ok=True)
    wheel_path = directory / filename
    wheel_path.write_bytes(b"fake wheel content")
    return wheel_path


class TestLocalDirectoryBackend:
    def test_name(self, tmp_path: pathlib.Path) -> None:
        backend = LocalDirectoryBackend(
            tmp_path / "wheels", backend_name="local:default"
        )
        assert backend.name == "local:default"

    def test_writable(self, tmp_path: pathlib.Path) -> None:
        backend = LocalDirectoryBackend(tmp_path / "wheels")
        assert backend.writable is True

    def test_scan_empty_directory(self, tmp_path: pathlib.Path) -> None:
        wheels_dir = tmp_path / "wheels"
        wheels_dir.mkdir()
        backend = LocalDirectoryBackend(wheels_dir)
        result = backend.scan()
        assert result == {}

    def test_scan_nonexistent_directory(self, tmp_path: pathlib.Path) -> None:
        backend = LocalDirectoryBackend(tmp_path / "nonexistent")
        result = backend.scan()
        assert result == {}

    def test_scan_finds_wheels(self, tmp_path: pathlib.Path) -> None:
        wheels_dir = tmp_path / "wheels"
        _create_wheel_file(wheels_dir, "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl")
        backend = LocalDirectoryBackend(wheels_dir)
        result = backend.scan()

        expected_key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        assert expected_key in result
        assert (
            result[expected_key].filename
            == "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl"
        )

    def test_scan_skips_non_wheel_files(self, tmp_path: pathlib.Path) -> None:
        wheels_dir = tmp_path / "wheels"
        wheels_dir.mkdir()
        (wheels_dir / "readme.txt").write_text("not a wheel")
        (wheels_dir / "numpy-1.26.4.tar.gz").write_bytes(b"sdist")
        backend = LocalDirectoryBackend(wheels_dir)
        result = backend.scan()
        assert result == {}

    def test_scan_skips_unparseable_wheels(self, tmp_path: pathlib.Path) -> None:
        wheels_dir = tmp_path / "wheels"
        wheels_dir.mkdir()
        (wheels_dir / "totally-invalid-name.whl").write_bytes(b"bad")
        backend = LocalDirectoryBackend(wheels_dir)
        result = backend.scan()
        assert result == {}

    def test_lookup_hit(self, tmp_path: pathlib.Path) -> None:
        wheels_dir = tmp_path / "wheels"
        _create_wheel_file(wheels_dir, "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl")
        backend = LocalDirectoryBackend(wheels_dir)
        backend.scan()

        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        result = backend.lookup(key)
        assert result is not None
        assert result.filename == "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl"

    def test_lookup_miss(self, tmp_path: pathlib.Path) -> None:
        wheels_dir = tmp_path / "wheels"
        wheels_dir.mkdir()
        backend = LocalDirectoryBackend(wheels_dir)
        backend.scan()

        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        assert backend.lookup(key) is None

    def test_lookup_evicts_deleted_file(self, tmp_path: pathlib.Path) -> None:
        wheels_dir = tmp_path / "wheels"
        whl = _create_wheel_file(
            wheels_dir, "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl"
        )
        backend = LocalDirectoryBackend(wheels_dir)
        backend.scan()

        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        # File exists initially
        assert backend.lookup(key) is not None
        # Delete it
        whl.unlink()
        # Now lookup should return None and evict from index
        assert backend.lookup(key) is None

    def test_fetch_returns_local_path(self, tmp_path: pathlib.Path) -> None:
        wheels_dir = tmp_path / "wheels"
        whl = _create_wheel_file(
            wheels_dir, "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl"
        )
        backend = LocalDirectoryBackend(wheels_dir)
        backend.scan()

        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        info = backend.lookup(key)
        assert info is not None
        result = backend.fetch(key, info, tmp_path / "dest")
        assert result == whl.resolve()

    def test_store_copies_file(self, tmp_path: pathlib.Path) -> None:
        """Store copies the wheel to the collection directory, preserving the original."""
        wheels_dir = tmp_path / "wheels"
        wheels_dir.mkdir()
        backend = LocalDirectoryBackend(wheels_dir)
        backend.scan()

        # Create a wheel in a "build" directory
        build_dir = tmp_path / "build"
        whl = _create_wheel_file(build_dir, "requests-2.31.0-1-py3-none-any.whl")

        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        info = backend.store(key, whl)

        assert info.filename == "requests-2.31.0-1-py3-none-any.whl"
        assert (wheels_dir / "requests-2.31.0-1-py3-none-any.whl").exists()
        assert whl.exists()  # Original preserved for internal wheel server

    def test_store_updates_index(self, tmp_path: pathlib.Path) -> None:
        wheels_dir = tmp_path / "wheels"
        wheels_dir.mkdir()
        backend = LocalDirectoryBackend(wheels_dir)
        backend.scan()

        build_dir = tmp_path / "build"
        whl = _create_wheel_file(build_dir, "requests-2.31.0-1-py3-none-any.whl")

        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        backend.store(key, whl)

        # Should be findable via lookup now
        result = backend.lookup(key)
        assert result is not None
        assert result.filename == "requests-2.31.0-1-py3-none-any.whl"

    def test_store_no_move_if_already_exists(self, tmp_path: pathlib.Path) -> None:
        wheels_dir = tmp_path / "wheels"
        existing = _create_wheel_file(wheels_dir, "requests-2.31.0-1-py3-none-any.whl")
        backend = LocalDirectoryBackend(wheels_dir)
        backend.scan()

        key = WheelCacheKey(
            package=canonicalize_name("requests"),
            version=Version("2.31.0"),
            build_tag=(1, ""),
        )
        # Store with same filename that already exists
        info = backend.store(key, existing)
        assert info.filename == "requests-2.31.0-1-py3-none-any.whl"
        assert existing.exists()


# ---------------------------------------------------------------------------
# RemotePEP503Backend tests
# ---------------------------------------------------------------------------


class TestRemotePEP503Backend:
    def test_name_default(self) -> None:
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=pathlib.Path("/tmp/downloads"),
        )
        assert backend.name == "remote:https://cache.test/simple"

    def test_not_writable(self) -> None:
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=pathlib.Path("/tmp/downloads"),
        )
        assert backend.writable is False

    def test_store_raises(self) -> None:
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=pathlib.Path("/tmp/downloads"),
        )
        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        with pytest.raises(NotImplementedError):
            backend.store(key, pathlib.Path("/fake.whl"))

    def test_parse_index_page(self) -> None:
        html = """
        <!DOCTYPE html>
        <html><body>
        <a href="numpy/">numpy</a>
        <a href="requests/">requests</a>
        <a href="flask/">Flask</a>
        </body></html>
        """
        result = RemotePEP503Backend._parse_index_page(html)
        assert canonicalize_name("numpy") in result
        assert canonicalize_name("requests") in result
        assert canonicalize_name("flask") in result

    def test_parse_project_page(self) -> None:
        html = """
        <!DOCTYPE html>
        <html><body>
        <a href="numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl#sha256=abc123">numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl</a>
        <a href="numpy-1.26.4.tar.gz">numpy-1.26.4.tar.gz</a>
        <a href="/files/numpy-1.25.0-cp312-cp312-linux_x86_64.whl">numpy-1.25.0-cp312-cp312-linux_x86_64.whl</a>
        </body></html>
        """
        result = RemotePEP503Backend._parse_project_page(
            html, "https://cache.test/simple/numpy/"
        )
        assert len(result) == 2  # Only .whl files
        assert result[0].filename == "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl"
        assert result[0].sha256 == "abc123"
        assert result[1].filename == "numpy-1.25.0-cp312-cp312-linux_x86_64.whl"
        assert "cache.test" in result[1].url_or_path

    def test_parse_project_page_absolute_url(self) -> None:
        html = '<a href="https://other.test/numpy-1.26.4-cp312-cp312-linux_x86_64.whl">numpy-1.26.4-cp312-cp312-linux_x86_64.whl</a>'
        result = RemotePEP503Backend._parse_project_page(
            html, "https://cache.test/simple/numpy/"
        )
        assert len(result) == 1
        assert (
            result[0].url_or_path
            == "https://other.test/numpy-1.26.4-cp312-cp312-linux_x86_64.whl"
        )

    def test_lookup_short_circuits_unknown_package(self) -> None:
        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=pathlib.Path("/tmp"),
        )
        # Simulate scan() having populated the available packages set
        backend._available_packages = {canonicalize_name("requests")}

        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        assert backend.lookup(key) is None

    def test_scan_populates_available_packages(
        self, requests_mock: requests_mock.Mocker
    ) -> None:
        """scan() fetches the index page and populates available_packages."""
        index_html = """
        <!DOCTYPE html><html><body>
        <a href="numpy/">numpy</a>
        <a href="torch/">torch</a>
        </body></html>
        """
        requests_mock.get("https://cache.test/simple/", text=index_html)

        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=pathlib.Path("/tmp"),
        )
        result = backend.scan()

        assert result == {}
        assert backend._available_packages is not None
        assert canonicalize_name("numpy") in backend._available_packages
        assert canonicalize_name("torch") in backend._available_packages
        assert len(backend._available_packages) == 2

    def test_scan_handles_network_error(
        self, requests_mock: requests_mock.Mocker
    ) -> None:
        """scan() gracefully handles a network error."""
        import requests

        requests_mock.get(
            "https://cache.test/simple/", exc=requests.ConnectionError("timeout")
        )

        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=pathlib.Path("/tmp"),
        )
        result = backend.scan()

        assert result == {}
        assert backend._available_packages == set()

    def test_lookup_fetches_project_page_lazily(
        self, requests_mock: requests_mock.Mocker
    ) -> None:
        """lookup() fetches the project page on first access and caches it."""
        project_html = """
        <a href="numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl#sha256=abc">numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl</a>
        """
        requests_mock.get("https://cache.test/simple/numpy/", text=project_html)

        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=pathlib.Path("/tmp"),
        )
        backend._available_packages = {canonicalize_name("numpy")}

        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        info = backend.lookup(key)

        assert info is not None
        assert info.filename == "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl"
        assert info.sha256 == "abc"
        # Project page is now cached
        assert canonicalize_name("numpy") in backend._project_cache

    def test_lookup_returns_none_for_unmatched_version(
        self, requests_mock: requests_mock.Mocker
    ) -> None:
        """lookup() returns None when version doesn't match any wheel."""
        project_html = """
        <a href="numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl">numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl</a>
        """
        requests_mock.get("https://cache.test/simple/numpy/", text=project_html)

        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=pathlib.Path("/tmp"),
        )
        backend._available_packages = {canonicalize_name("numpy")}

        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("2.0.0"),
            build_tag=(1, ""),
        )
        assert backend.lookup(key) is None

    def test_lookup_caches_project_page(
        self, requests_mock: requests_mock.Mocker
    ) -> None:
        """Second lookup() for same package does not fetch again."""
        project_html = """
        <a href="numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl">numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl</a>
        """
        requests_mock.get("https://cache.test/simple/numpy/", text=project_html)

        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=pathlib.Path("/tmp"),
        )
        backend._available_packages = {canonicalize_name("numpy")}

        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        backend.lookup(key)
        backend.lookup(key)

        # Only one request made to the project page
        assert requests_mock.call_count == 1

    def test_fetch_downloads_wheel(
        self, tmp_path: pathlib.Path, requests_mock: requests_mock.Mocker
    ) -> None:
        """fetch() downloads wheel content to the destination directory."""
        wheel_content = b"PK\x03\x04fake wheel archive content"
        requests_mock.get(
            "https://cache.test/files/numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl",
            content=wheel_content,
        )

        from fromager.cache import ArtifactInfo

        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path / "downloads",
        )
        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        info = ArtifactInfo(
            filename="numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl",
            url_or_path="https://cache.test/files/numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl",
        )

        dest = tmp_path / "dest"
        result_path = backend.fetch(key, info, dest)

        assert result_path.exists()
        assert result_path.name == "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl"
        assert result_path.read_bytes() == wheel_content

    def test_fetch_skips_existing_file(self, tmp_path: pathlib.Path) -> None:
        """fetch() returns existing path without downloading if file exists."""
        from fromager.cache import ArtifactInfo

        dest = tmp_path / "dest"
        dest.mkdir()
        existing = dest / "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl"
        existing.write_bytes(b"existing content")

        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path / "downloads",
        )
        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        info = ArtifactInfo(
            filename="numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl",
            url_or_path="https://cache.test/files/numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl",
        )

        result_path = backend.fetch(key, info, dest)

        assert result_path == existing
        assert result_path.read_bytes() == b"existing content"

    def test_full_scan_lookup_fetch_flow(
        self,
        tmp_path: pathlib.Path,
        requests_mock: requests_mock.Mocker,
    ) -> None:
        """End-to-end: scan -> lookup -> fetch for a remote backend."""
        wheel_content = b"wheel bytes"
        wheel_sha256 = (
            "67c0d8f7de19e30c2d5891030a0b37cbfcdd240852b53055c0b28290ad52290b"
        )
        index_html = '<a href="numpy/">numpy</a>'
        project_html = f"""
        <a href="https://cache.test/files/numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl#sha256={wheel_sha256}">numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl</a>
        """

        requests_mock.get("https://cache.test/simple/", text=index_html)
        requests_mock.get("https://cache.test/simple/numpy/", text=project_html)
        requests_mock.get(
            "https://cache.test/files/numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl",
            content=wheel_content,
        )

        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path / "downloads",
        )

        # Step 1: scan
        backend.scan()
        assert backend._available_packages is not None
        assert canonicalize_name("numpy") in backend._available_packages

        # Step 2: lookup
        key = WheelCacheKey(
            package=canonicalize_name("numpy"),
            version=Version("1.26.4"),
            build_tag=(2, ""),
        )
        info = backend.lookup(key)
        assert info is not None
        assert info.sha256 == wheel_sha256

        # Step 3: fetch
        dest = tmp_path / "local-cache"
        result_path = backend.fetch(key, info, dest)
        assert result_path.exists()
        assert result_path.read_bytes() == wheel_content

    def test_fetch_rejects_sha256_mismatch(
        self,
        tmp_path: pathlib.Path,
        requests_mock: requests_mock.Mocker,
    ) -> None:
        """Fetch raises ValueError and removes file on sha256 mismatch."""
        project_html = """
        <a href="https://cache.test/files/bad-1.0-1-py3-none-any.whl#sha256=badhash">bad-1.0-1-py3-none-any.whl</a>
        """
        requests_mock.get("https://cache.test/simple/", text='<a href="bad/">bad</a>')
        requests_mock.get("https://cache.test/simple/bad/", text=project_html)
        requests_mock.get(
            "https://cache.test/files/bad-1.0-1-py3-none-any.whl",
            content=b"tampered content",
        )

        backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path / "downloads",
        )
        backend.scan()

        key = WheelCacheKey(
            package=canonicalize_name("bad"),
            version=Version("1.0"),
            build_tag=(1, ""),
        )
        info = backend.lookup(key)
        assert info is not None

        import pytest

        dest = tmp_path / "local-cache"
        with pytest.raises(ValueError, match="sha256 mismatch"):
            backend.fetch(key, info, dest)
        assert not (dest / "bad-1.0-1-py3-none-any.whl").exists()

    def test_parse_project_page_rejects_path_traversal(self) -> None:
        """Filenames with path components are rejected."""
        html = """
        <a href="../../etc/evil.whl">../../etc/evil.whl</a>
        <a href="good-1.0-1-py3-none-any.whl">good-1.0-1-py3-none-any.whl</a>
        """
        artifacts = RemotePEP503Backend._parse_project_page(
            html, "https://cache.test/simple/pkg/"
        )
        assert len(artifacts) == 1
        assert artifacts[0].filename == "good-1.0-1-py3-none-any.whl"


# ---------------------------------------------------------------------------
# StoreRouter tests
# ---------------------------------------------------------------------------


class TestStoreRouter:
    def test_override_wins(self) -> None:
        router = StoreRouter(
            overrides={canonicalize_name("torch"): "cuda"},
            accelerated_packages=set(),
            active_variant="cuda",
        )
        req = Requirement("torch>=2.0")
        assert router.route(req) == "cuda"

    def test_accelerated_package(self) -> None:
        router = StoreRouter(
            overrides={},
            accelerated_packages={canonicalize_name("flash-attn")},
            active_variant="cuda",
        )
        req = Requirement("flash-attn>=2.0")
        assert router.route(req) == "cuda"

    def test_default_fallback(self) -> None:
        router = StoreRouter(
            overrides={},
            accelerated_packages={canonicalize_name("torch")},
            active_variant="cuda",
        )
        req = Requirement("requests>=2.0")
        assert router.route(req) == "default"

    def test_override_takes_priority_over_accelerated(self) -> None:
        router = StoreRouter(
            overrides={canonicalize_name("numpy"): "default"},
            accelerated_packages={canonicalize_name("numpy")},
            active_variant="cuda",
        )
        req = Requirement("numpy>=1.0")
        assert router.route(req) == "default"

    def test_custom_default_collection(self) -> None:
        router = StoreRouter(
            overrides={},
            accelerated_packages=set(),
            active_variant="rocm",
            default_collection="base",
        )
        req = Requirement("six")
        assert router.route(req) == "base"


# ---------------------------------------------------------------------------
# CacheManager tests
# ---------------------------------------------------------------------------


def _make_collection(tmp_path: pathlib.Path, name: str) -> CacheCollection:
    """Create a CacheCollection with a single local backend."""
    wheels_dir = tmp_path / f"wheels-{name}"
    wheels_dir.mkdir(parents=True, exist_ok=True)
    backend = LocalDirectoryBackend(wheels_dir, backend_name=f"local:{name}")
    return CacheCollection(
        name=name,
        backends=[backend],
        store_backend=backend,
    )


class TestCacheManager:
    def test_lookup_miss_empty_cache(self, tmp_path: pathlib.Path) -> None:
        default = _make_collection(tmp_path, "default")
        manager = CacheManager(
            collections={"default": default},
            search_order=["default"],
            store_routing=StoreRouter(
                overrides={},
                accelerated_packages=set(),
                active_variant="cpu",
            ),
        )
        manager.initialize()

        result = manager.lookup_wheel(
            Requirement("numpy"),
            Version("1.26.4"),
            build_tag=(2, ""),
        )
        assert result.hit is False
        assert result.miss is True

    def test_lookup_hit_local(self, tmp_path: pathlib.Path) -> None:
        default = _make_collection(tmp_path, "default")
        _create_wheel_file(
            tmp_path / "wheels-default",
            "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl",
        )
        manager = CacheManager(
            collections={"default": default},
            search_order=["default"],
            store_routing=StoreRouter(
                overrides={},
                accelerated_packages=set(),
                active_variant="cpu",
            ),
        )
        manager.initialize()

        result = manager.lookup_wheel(
            Requirement("numpy"),
            Version("1.26.4"),
            build_tag=(2, ""),
        )
        assert result.hit is True
        assert result.collection == "default"
        assert result.backend_name == "local:default"
        assert result.path is not None

    def test_lookup_respects_search_order(self, tmp_path: pathlib.Path) -> None:
        """CUDA collection is searched first, default second."""
        cuda = _make_collection(tmp_path, "cuda")
        default = _make_collection(tmp_path, "default")

        # Put the wheel only in default
        _create_wheel_file(
            tmp_path / "wheels-default",
            "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl",
        )

        manager = CacheManager(
            collections={"cuda": cuda, "default": default},
            search_order=["cuda", "default"],
            store_routing=StoreRouter(
                overrides={},
                accelerated_packages=set(),
                active_variant="cuda",
            ),
        )
        manager.initialize()

        result = manager.lookup_wheel(
            Requirement("numpy"),
            Version("1.26.4"),
            build_tag=(2, ""),
        )
        assert result.hit is True
        assert result.collection == "default"

    def test_lookup_variant_collection_takes_priority(
        self, tmp_path: pathlib.Path
    ) -> None:
        """When wheel exists in both, variant collection wins."""
        cuda = _make_collection(tmp_path, "cuda")
        default = _make_collection(tmp_path, "default")

        _create_wheel_file(
            tmp_path / "wheels-cuda",
            "torch-2.10.0-7-cp312-cp312-linux_x86_64.whl",
        )
        _create_wheel_file(
            tmp_path / "wheels-default",
            "torch-2.10.0-7-cp312-cp312-linux_x86_64.whl",
        )

        manager = CacheManager(
            collections={"cuda": cuda, "default": default},
            search_order=["cuda", "default"],
            store_routing=StoreRouter(
                overrides={},
                accelerated_packages=set(),
                active_variant="cuda",
            ),
        )
        manager.initialize()

        result = manager.lookup_wheel(
            Requirement("torch"),
            Version("2.10.0"),
            build_tag=(7, ""),
        )
        assert result.hit is True
        assert result.collection == "cuda"

    def test_force_skips_lookup(self, tmp_path: pathlib.Path) -> None:
        default = _make_collection(tmp_path, "default")
        _create_wheel_file(
            tmp_path / "wheels-default",
            "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl",
        )
        manager = CacheManager(
            collections={"default": default},
            search_order=["default"],
            store_routing=StoreRouter(
                overrides={},
                accelerated_packages=set(),
                active_variant="cpu",
            ),
            force=True,
        )
        manager.initialize()

        result = manager.lookup_wheel(
            Requirement("numpy"),
            Version("1.26.4"),
            build_tag=(2, ""),
        )
        assert result.hit is False

    def test_store_routes_to_correct_collection(self, tmp_path: pathlib.Path) -> None:
        cuda = _make_collection(tmp_path, "cuda")
        default = _make_collection(tmp_path, "default")

        build_dir = tmp_path / "build"
        whl = _create_wheel_file(
            build_dir, "torch-2.10.0-7-cp312-cp312-linux_x86_64.whl"
        )

        manager = CacheManager(
            collections={"cuda": cuda, "default": default},
            search_order=["cuda", "default"],
            store_routing=StoreRouter(
                overrides={},
                accelerated_packages={canonicalize_name("torch")},
                active_variant="cuda",
            ),
        )
        manager.initialize()

        result_path = manager.store_wheel(
            Requirement("torch"),
            Version("2.10.0"),
            build_tag=(7, ""),
            wheel_path=whl,
        )

        # Should be stored in cuda collection
        assert "wheels-cuda" in str(result_path)
        assert (
            tmp_path / "wheels-cuda" / "torch-2.10.0-7-cp312-cp312-linux_x86_64.whl"
        ).exists()

    def test_store_default_collection(self, tmp_path: pathlib.Path) -> None:
        cuda = _make_collection(tmp_path, "cuda")
        default = _make_collection(tmp_path, "default")

        build_dir = tmp_path / "build"
        whl = _create_wheel_file(build_dir, "requests-2.31.0-1-py3-none-any.whl")

        manager = CacheManager(
            collections={"cuda": cuda, "default": default},
            search_order=["cuda", "default"],
            store_routing=StoreRouter(
                overrides={},
                accelerated_packages={canonicalize_name("torch")},
                active_variant="cuda",
            ),
        )
        manager.initialize()

        result_path = manager.store_wheel(
            Requirement("requests"),
            Version("2.31.0"),
            build_tag=(1, ""),
            wheel_path=whl,
        )

        assert "wheels-default" in str(result_path)

    def test_store_then_lookup(self, tmp_path: pathlib.Path) -> None:
        """A stored wheel is immediately findable via lookup."""
        default = _make_collection(tmp_path, "default")

        build_dir = tmp_path / "build"
        whl = _create_wheel_file(build_dir, "requests-2.31.0-1-py3-none-any.whl")

        manager = CacheManager(
            collections={"default": default},
            search_order=["default"],
            store_routing=StoreRouter(
                overrides={},
                accelerated_packages=set(),
                active_variant="cpu",
            ),
        )
        manager.initialize()

        manager.store_wheel(
            Requirement("requests"),
            Version("2.31.0"),
            build_tag=(1, ""),
            wheel_path=whl,
        )

        result = manager.lookup_wheel(
            Requirement("requests"),
            Version("2.31.0"),
            build_tag=(1, ""),
        )
        assert result.hit is True

    def test_store_unknown_collection_raises(self, tmp_path: pathlib.Path) -> None:
        default = _make_collection(tmp_path, "default")
        build_dir = tmp_path / "build"
        whl = _create_wheel_file(
            build_dir, "torch-2.10.0-7-cp312-cp312-linux_x86_64.whl"
        )

        manager = CacheManager(
            collections={"default": default},
            search_order=["default"],
            store_routing=StoreRouter(
                overrides={},
                accelerated_packages={canonicalize_name("torch")},
                active_variant="cuda",  # No "cuda" collection configured
            ),
        )
        manager.initialize()

        with pytest.raises(ValueError, match="unknown collection"):
            manager.store_wheel(
                Requirement("torch"),
                Version("2.10.0"),
                build_tag=(7, ""),
                wheel_path=whl,
            )


# ---------------------------------------------------------------------------
# CacheStats tests
# ---------------------------------------------------------------------------


class TestCacheStats:
    def test_empty_stats(self) -> None:
        stats = CacheStats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.stores == 0
        assert stats.hit_rate == 0.0

    def test_record_hit(self) -> None:
        stats = CacheStats()
        stats.record_hit(Requirement("numpy"), Version("1.26.4"), "default", "local")
        assert stats.hits == 1
        assert stats.misses == 0

    def test_record_miss(self) -> None:
        stats = CacheStats()
        stats.record_miss(Requirement("numpy"), Version("1.26.4"), "not_found")
        assert stats.misses == 1
        assert stats.hits == 0

    def test_hit_rate(self) -> None:
        stats = CacheStats()
        stats.record_hit(Requirement("numpy"), Version("1.26.4"), "default", "local")
        stats.record_hit(Requirement("requests"), Version("2.31.0"), "default", "local")
        stats.record_miss(Requirement("torch"), Version("2.10.0"), "not_found")
        assert stats.hit_rate == pytest.approx(2 / 3)

    def test_summary(self) -> None:
        stats = CacheStats()
        stats.record_hit(
            Requirement("numpy"), Version("1.26.4"), "default", "local:default"
        )
        stats.record_miss(Requirement("torch"), Version("2.10.0"), "not_found")
        stats.record_store(Requirement("torch"), Version("2.10.0"), "cuda")

        summary = stats.summary()
        assert summary["hits"]["total"] == 1
        assert summary["hits"]["by_collection"]["default"] == 1
        assert summary["misses"] == 1
        assert summary["stores"] == 1


# ---------------------------------------------------------------------------
# CacheResult tests
# ---------------------------------------------------------------------------


class TestCacheResult:
    def test_miss_property(self) -> None:
        result = CacheResult(hit=False)
        assert result.miss is True
        assert result.hit is False

    def test_hit_result(self) -> None:
        result = CacheResult(
            hit=True,
            path=pathlib.Path("/some/wheel.whl"),
            collection="default",
            backend_name="local:default",
        )
        assert result.miss is False
        assert result.path == pathlib.Path("/some/wheel.whl")


# ---------------------------------------------------------------------------
# CacheManager + RemotePEP503Backend integration tests
# ---------------------------------------------------------------------------


class TestCacheManagerRemoteIntegration:
    """Integration tests verifying CacheManager with remote backends."""

    def test_remote_hit_downloads_to_local_store(
        self,
        tmp_path: pathlib.Path,
        requests_mock: requests_mock.Mocker,
    ) -> None:
        """CacheManager lookup via remote backend downloads wheel locally."""

        # Set up remote backend with a wheel available
        wheel_content = b"remote wheel content"
        wheel_sha = "afb823df34d54af96bcc9a759d34c85fc14f30840bf45377ef911e68be9569df"
        project_html = f"""
        <a href="https://cache.test/files/numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl#sha256={wheel_sha}">numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl</a>
        """
        requests_mock.get(
            "https://cache.test/simple/", text='<a href="numpy/">numpy</a>'
        )
        requests_mock.get("https://cache.test/simple/numpy/", text=project_html)
        requests_mock.get(
            "https://cache.test/files/numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl",
            content=wheel_content,
        )

        local_dir = tmp_path / "local-wheels"
        local_dir.mkdir()
        local_backend = LocalDirectoryBackend(local_dir, backend_name="local:default")

        remote_backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path / "downloads",
        )

        collection = CacheCollection(
            name="default",
            backends=[local_backend, remote_backend],
            store_backend=local_backend,
        )
        router = StoreRouter(
            overrides={}, accelerated_packages=set(), active_variant="cpu"
        )
        manager = CacheManager(
            collections={"default": collection},
            search_order=["default"],
            store_routing=router,
        )
        manager.initialize()

        # Lookup should miss local, hit remote, and download
        result = manager.lookup_wheel(
            Requirement("numpy"),
            Version("1.26.4"),
            build_tag=(2, ""),
        )

        assert result.hit is True
        assert result.path is not None
        assert result.path.exists()
        assert result.path.read_bytes() == wheel_content
        assert result.backend_name == "remote:https://cache.test/simple"
        assert result.was_downloaded is True

    def test_local_hit_takes_priority_over_remote(
        self,
        tmp_path: pathlib.Path,
        requests_mock: requests_mock.Mocker,
    ) -> None:
        """Local backend hit means remote is never consulted."""
        local_dir = tmp_path / "local-wheels"
        local_dir.mkdir()
        # Put a wheel in the local cache
        wheel_file = local_dir / "numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl"
        wheel_file.write_bytes(b"local wheel")

        local_backend = LocalDirectoryBackend(local_dir, backend_name="local:default")
        remote_backend = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path / "downloads",
        )

        # Don't register any requests_mock responses — remote should not be hit
        requests_mock.get(
            "https://cache.test/simple/", text='<a href="numpy/">numpy</a>'
        )

        collection = CacheCollection(
            name="default",
            backends=[local_backend, remote_backend],
            store_backend=local_backend,
        )
        router = StoreRouter(
            overrides={}, accelerated_packages=set(), active_variant="cpu"
        )
        manager = CacheManager(
            collections={"default": collection},
            search_order=["default"],
            store_routing=router,
        )
        manager.initialize()

        result = manager.lookup_wheel(
            Requirement("numpy"),
            Version("1.26.4"),
            build_tag=(2, ""),
        )

        assert result.hit is True
        assert result.path == wheel_file
        assert result.backend_name == "local:default"
        assert result.was_downloaded is False
        # Remote project page never fetched
        assert not any("simple/numpy/" in h.url for h in requests_mock.request_history)

    def test_hierarchical_search_across_collections_with_remote(
        self,
        tmp_path: pathlib.Path,
        requests_mock: requests_mock.Mocker,
    ) -> None:
        """CacheManager searches variant collection first, then falls through to default."""
        # CUDA collection: empty (no local, remote has nothing matching)
        cuda_local = tmp_path / "cuda-wheels"
        cuda_local.mkdir()
        cuda_backend = LocalDirectoryBackend(cuda_local, backend_name="local:cuda")

        # Default collection: has numpy via remote
        default_local = tmp_path / "default-wheels"
        default_local.mkdir()
        default_backend = LocalDirectoryBackend(
            default_local, backend_name="local:default"
        )

        project_html = """
        <a href="https://cache.test/files/numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl">numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl</a>
        """
        requests_mock.get(
            "https://cache.test/simple/", text='<a href="numpy/">numpy</a>'
        )
        requests_mock.get("https://cache.test/simple/numpy/", text=project_html)
        requests_mock.get(
            "https://cache.test/files/numpy-1.26.4-2-cp312-cp312-linux_x86_64.whl",
            content=b"remote numpy",
        )

        remote_default = RemotePEP503Backend(
            server_url="https://cache.test/simple",
            download_dir=tmp_path / "downloads",
        )

        cuda_collection = CacheCollection(
            name="cuda",
            backends=[cuda_backend],
            store_backend=cuda_backend,
        )
        default_collection = CacheCollection(
            name="default",
            backends=[default_backend, remote_default],
            store_backend=default_backend,
        )

        router = StoreRouter(
            overrides={},
            accelerated_packages={canonicalize_name("torch")},
            active_variant="cuda",
        )
        manager = CacheManager(
            collections={"cuda": cuda_collection, "default": default_collection},
            search_order=["cuda", "default"],
            store_routing=router,
        )
        manager.initialize()

        # numpy is not in cuda, should be found in default via remote
        result = manager.lookup_wheel(
            Requirement("numpy"),
            Version("1.26.4"),
            build_tag=(2, ""),
        )

        assert result.hit is True
        assert result.collection == "default"
        assert result.path is not None
        assert result.path.read_bytes() == b"remote numpy"
