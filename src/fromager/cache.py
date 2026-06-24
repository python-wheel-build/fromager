"""Unified cache subsystem for Fromager artifact management.

Provides a layered cache with collection-based organization, supporting
hierarchical lookup across local directories and remote PEP 503 repositories.

Collections represent logically grouped artifacts (e.g., "default", "cuda",
"rocm"). Each collection has one or more backends (local filesystem, remote
index). Lookups traverse collections in priority order, and store routing
determines which collection receives newly built artifacts.
"""

from __future__ import annotations

import dataclasses
import logging
import pathlib
import re
import shutil
import time
import typing
from urllib.parse import urlparse

from packaging.requirements import Requirement
from packaging.utils import (
    BuildTag,
    NormalizedName,
    canonicalize_name,
    parse_wheel_filename,
)
from packaging.version import Version

from .request_session import session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache Keys
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class WheelCacheKey:
    """Identifies a cached wheel artifact.

    The key is intentionally simple -- collection routing is handled
    externally by the CacheManager, not embedded in the key.
    """

    package: NormalizedName
    version: Version
    build_tag: BuildTag  # (int, str) from changelog; () if untagged

    def __str__(self) -> str:
        tag_str = f"-{self.build_tag[0]}{self.build_tag[1]}" if self.build_tag else ""
        return f"{self.package}=={self.version}{tag_str}"


@dataclasses.dataclass(frozen=True)
class SdistCacheKey:
    """Identifies a cached sdist artifact."""

    package: NormalizedName
    version: Version

    def __str__(self) -> str:
        return f"{self.package}=={self.version}"


# ---------------------------------------------------------------------------
# Artifact Metadata
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ArtifactInfo:
    """Lightweight metadata for a cached artifact.

    Produced by scanning backends. For local backends, ``url_or_path`` is
    an absolute filesystem path. For remote backends, it is a download URL.
    """

    filename: str
    url_or_path: str
    size_bytes: int | None = None
    sha256: str | None = None


# ---------------------------------------------------------------------------
# Cache Result
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CacheResult:
    """Result of a cache lookup operation."""

    hit: bool
    path: pathlib.Path | None = None
    collection: str = ""
    backend_name: str = ""
    build_tag: BuildTag = ()
    was_downloaded: bool = False

    @property
    def miss(self) -> bool:
        return not self.hit


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CacheEvent:
    """A single cache interaction event."""

    timestamp: float
    action: typing.Literal["hit", "miss", "store"]
    artifact_type: typing.Literal["wheel", "sdist"]
    package: str
    version: str
    collection: str
    backend: str
    duration_ms: float | None = None


@dataclasses.dataclass
class CacheStats:
    """Accumulates cache events for a single run."""

    events: list[CacheEvent] = dataclasses.field(default_factory=list)

    def record_hit(
        self,
        req: Requirement,
        version: Version,
        collection: str,
        backend: str,
        artifact_type: typing.Literal["wheel", "sdist"] = "wheel",
        duration_ms: float | None = None,
    ) -> None:
        self.events.append(
            CacheEvent(
                timestamp=time.monotonic(),
                action="hit",
                artifact_type=artifact_type,
                package=str(req.name),
                version=str(version),
                collection=collection,
                backend=backend,
                duration_ms=duration_ms,
            )
        )

    def record_miss(
        self,
        req: Requirement,
        version: Version,
        reason: str,
        artifact_type: typing.Literal["wheel", "sdist"] = "wheel",
    ) -> None:
        self.events.append(
            CacheEvent(
                timestamp=time.monotonic(),
                action="miss",
                artifact_type=artifact_type,
                package=str(req.name),
                version=str(version),
                collection="",
                backend=reason,
            )
        )

    def record_store(
        self,
        req: Requirement,
        version: Version,
        collection: str,
        artifact_type: typing.Literal["wheel", "sdist"] = "wheel",
    ) -> None:
        self.events.append(
            CacheEvent(
                timestamp=time.monotonic(),
                action="store",
                artifact_type=artifact_type,
                package=str(req.name),
                version=str(version),
                collection=collection,
                backend="local",
            )
        )

    @property
    def hits(self) -> int:
        return sum(1 for e in self.events if e.action == "hit")

    @property
    def misses(self) -> int:
        return sum(1 for e in self.events if e.action == "miss")

    @property
    def stores(self) -> int:
        return sum(1 for e in self.events if e.action == "store")

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total

    def summary(self) -> dict[str, typing.Any]:
        """Return a structured summary suitable for JSON serialization."""
        hits_by_collection: dict[str, int] = {}
        hits_by_backend: dict[str, int] = {}
        for e in self.events:
            if e.action == "hit":
                hits_by_collection[e.collection] = (
                    hits_by_collection.get(e.collection, 0) + 1
                )
                hits_by_backend[e.backend] = hits_by_backend.get(e.backend, 0) + 1
        return {
            "hits": {
                "total": self.hits,
                "by_collection": hits_by_collection,
                "by_backend": hits_by_backend,
            },
            "misses": self.misses,
            "stores": self.stores,
            "hit_rate": round(self.hit_rate, 4),
        }


# ---------------------------------------------------------------------------
# Cache Backend Protocol
# ---------------------------------------------------------------------------


class CacheBackend(typing.Protocol):
    """Protocol for a single storage location that can find and store artifacts."""

    @property
    def name(self) -> str:
        """Human-readable identifier (e.g., 'local:default', 'remote:https://...')."""
        ...

    @property
    def writable(self) -> bool:
        """Whether this backend supports store operations."""
        ...

    def scan(self) -> dict[WheelCacheKey, ArtifactInfo]:
        """Bulk index at startup. Local backends return full inventory;
        remote backends fetch the top-level package list only and return empty.
        """
        ...

    def lookup(self, key: WheelCacheKey) -> ArtifactInfo | None:
        """Find a specific artifact by key.

        For local backends, checks the in-memory index.
        For remote backends, lazily fetches the project page on first access.
        """
        ...

    def fetch(
        self, key: WheelCacheKey, info: ArtifactInfo, dest: pathlib.Path
    ) -> pathlib.Path:
        """Retrieve artifact to a local path.

        For local backends, returns the existing path (no-op).
        For remote backends, downloads the file to ``dest``.
        """
        ...

    def store(self, key: WheelCacheKey, artifact: pathlib.Path) -> ArtifactInfo:
        """Store a newly built artifact. Only valid if ``writable`` is True."""
        ...


# ---------------------------------------------------------------------------
# Local Directory Backend
# ---------------------------------------------------------------------------


class LocalDirectoryBackend:
    """Cache backend backed by a local filesystem directory.

    Scans at startup to populate an in-memory index from existing wheel files.
    New stores are reflected immediately in the index.
    """

    def __init__(
        self,
        directory: pathlib.Path,
        backend_name: str = "local",
    ) -> None:
        self._directory = directory
        self._backend_name = backend_name
        self._index: dict[WheelCacheKey, ArtifactInfo] = {}

    @property
    def name(self) -> str:
        return self._backend_name

    @property
    def writable(self) -> bool:
        return True

    @property
    def directory(self) -> pathlib.Path:
        return self._directory

    def scan(self) -> dict[WheelCacheKey, ArtifactInfo]:
        """Scan the directory for wheel files and populate the index."""
        self._index.clear()
        if not self._directory.exists():
            return self._index

        for wheel_file in self._directory.glob("*.whl"):
            try:
                name, version, build_tag, _ = parse_wheel_filename(wheel_file.name)
                key = WheelCacheKey(
                    package=name,
                    version=version,
                    build_tag=build_tag,
                )
                info = ArtifactInfo(
                    filename=wheel_file.name,
                    url_or_path=str(wheel_file.resolve()),
                    size_bytes=wheel_file.stat().st_size,
                )
                self._index[key] = info
            except Exception:
                logger.debug("skipping unparseable wheel file: %s", wheel_file.name)
        logger.debug("scanned %d wheels in %s", len(self._index), self._directory)
        return dict(self._index)

    def lookup(self, key: WheelCacheKey) -> ArtifactInfo | None:
        """Look up artifact in the in-memory index."""
        info = self._index.get(key)
        if info is not None:
            file_path = pathlib.Path(info.url_or_path)
            if file_path.exists():
                return info
            # File was removed since scan -- evict from index
            del self._index[key]
        return None

    def fetch(
        self, key: WheelCacheKey, info: ArtifactInfo, dest: pathlib.Path
    ) -> pathlib.Path:
        """Return the existing local path (no-op for local backends)."""
        return pathlib.Path(info.url_or_path)

    def store(self, key: WheelCacheKey, artifact: pathlib.Path) -> ArtifactInfo:
        """Register an artifact in this backend's directory.

        If the artifact is not already in the directory, it is copied there
        (preserving the original for the internal wheel server index).
        Updates the in-memory index.
        """
        dest = self._directory / artifact.name
        if not dest.exists():
            self._directory.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(artifact), str(dest))

        info = ArtifactInfo(
            filename=dest.name,
            url_or_path=str(dest.resolve()),
            size_bytes=dest.stat().st_size,
        )
        self._index[key] = info
        return info


# ---------------------------------------------------------------------------
# Remote PEP 503 Backend
# ---------------------------------------------------------------------------


class RemotePEP503Backend:
    """Cache backend backed by a remote PEP 503 (Simple Repository API) server.

    At startup, fetches the top-level package list. Individual project pages
    are fetched lazily on first lookup per package and memoized for the run.
    """

    def __init__(
        self,
        server_url: str,
        download_dir: pathlib.Path,
        backend_name: str | None = None,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._download_dir = download_dir
        self._backend_name = backend_name or f"remote:{self._server_url}"
        self._available_packages: set[NormalizedName] | None = None
        self._project_cache: dict[NormalizedName, list[ArtifactInfo]] = {}

    @property
    def name(self) -> str:
        return self._backend_name

    @property
    def writable(self) -> bool:
        return False

    def scan(self) -> dict[WheelCacheKey, ArtifactInfo]:
        """Fetch top-level index to learn which packages exist."""
        self._available_packages = self._fetch_package_list()
        logger.debug(
            "remote %s has %d packages available",
            self._server_url,
            len(self._available_packages) if self._available_packages else 0,
        )
        return {}

    def lookup(self, key: WheelCacheKey) -> ArtifactInfo | None:
        """Lazy per-package lookup with short-circuit for unknown packages."""
        if (
            self._available_packages is not None
            and key.package not in self._available_packages
        ):
            return None

        if key.package not in self._project_cache:
            self._project_cache[key.package] = self._fetch_project_page(key.package)

        for info in self._project_cache[key.package]:
            try:
                name, version, build_tag, _ = parse_wheel_filename(info.filename)
            except Exception:
                continue
            candidate_key = WheelCacheKey(
                package=name, version=version, build_tag=build_tag
            )
            if candidate_key == key:
                return info

        return None

    def fetch(
        self, key: WheelCacheKey, info: ArtifactInfo, dest: pathlib.Path
    ) -> pathlib.Path:
        """Download the wheel from the remote server."""
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / info.filename
        if target.exists():
            return target

        url = info.url_or_path
        logger.info(
            "downloading cached wheel %s from %s", info.filename, self._server_url
        )
        resp = session.get(url, stream=True)
        resp.raise_for_status()
        with open(target, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
        return target

    def store(self, key: WheelCacheKey, artifact: pathlib.Path) -> ArtifactInfo:
        """Not supported for remote backends."""
        raise NotImplementedError("Remote backends are read-only")

    def _fetch_package_list(self) -> set[NormalizedName]:
        """Fetch the top-level /simple/ index and extract package names."""
        url = f"{self._server_url}/"
        try:
            resp = session.get(url)
            resp.raise_for_status()
        except Exception as err:
            logger.warning("failed to fetch remote index %s: %s", url, err)
            return set()

        return self._parse_index_page(resp.text)

    def _fetch_project_page(self, package: NormalizedName) -> list[ArtifactInfo]:
        """Fetch a project's page and extract wheel artifact info."""
        url = f"{self._server_url}/{package}/"
        try:
            resp = session.get(url)
            resp.raise_for_status()
        except Exception as err:
            logger.debug("failed to fetch project page %s: %s", url, err)
            return []

        return self._parse_project_page(resp.text, url)

    @staticmethod
    def _parse_index_page(html: str) -> set[NormalizedName]:
        """Extract package names from a PEP 503 index page."""
        names: set[NormalizedName] = set()
        for match in re.finditer(r'<a\s+href="[^"]*">([^<]+)</a>', html):
            name = match.group(1).strip().rstrip("/")
            if name:
                names.add(canonicalize_name(name))
        return names

    @staticmethod
    def _parse_project_page(html: str, base_url: str) -> list[ArtifactInfo]:
        """Extract wheel artifact info from a PEP 503 project page."""
        artifacts: list[ArtifactInfo] = []
        for match in re.finditer(r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>', html):
            href = match.group(1)
            filename = match.group(2).strip()
            if not filename.endswith(".whl"):
                continue

            # Resolve relative URLs
            if href.startswith("http://") or href.startswith("https://"):
                url = href
            elif href.startswith("/"):
                parsed = urlparse(base_url)
                url = f"{parsed.scheme}://{parsed.netloc}{href}"
            else:
                url = base_url.rstrip("/") + "/" + href

            # Strip hash fragment for the URL but extract sha256 if present
            sha256 = None
            if "#" in url:
                url_part, fragment = url.rsplit("#", 1)
                if fragment.startswith("sha256="):
                    sha256 = fragment[7:]
                url = url_part

            artifacts.append(
                ArtifactInfo(
                    filename=filename,
                    url_or_path=url,
                    sha256=sha256,
                )
            )
        return artifacts


# ---------------------------------------------------------------------------
# Collection and Store Router
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CacheCollection:
    """A named group of artifacts with one or more backends."""

    name: str
    backends: list[CacheBackend]
    store_backend: LocalDirectoryBackend

    def scan_all(self) -> None:
        """Scan all backends in this collection."""
        for backend in self.backends:
            backend.scan()


class StoreRouter:
    """Determines which collection receives a newly built artifact.

    Routing priority:
    1. Explicit per-package override (from overrides.yaml)
    2. Listed in the variant's requirements file (variant_packages)
    3. Default collection (shared/common dependencies)
    """

    def __init__(
        self,
        overrides: dict[NormalizedName, str],
        variant_packages: set[NormalizedName] | None = None,
        active_variant: str = "cpu",
        default_collection: str = "default",
        # Keep old kwarg name for backward compatibility
        accelerated_packages: set[NormalizedName] | None = None,
    ) -> None:
        self._overrides = overrides
        self._variant_packages = variant_packages or accelerated_packages or set()
        self._active_variant = active_variant
        self._default_collection = default_collection

    def route(self, req: Requirement) -> str:
        """Return the collection name where this package should be stored."""
        name = canonicalize_name(req.name)

        if name in self._overrides:
            return self._overrides[name]

        if name in self._variant_packages:
            return self._active_variant

        return self._default_collection


# ---------------------------------------------------------------------------
# Cache Manager
# ---------------------------------------------------------------------------


class CacheManager:
    """Unified entry point for all cache operations.

    Owns collections, handles hierarchical lookup, routes stores,
    and tracks cache events for observability.
    """

    def __init__(
        self,
        collections: dict[str, CacheCollection],
        search_order: list[str],
        store_routing: StoreRouter,
        force: bool = False,
    ) -> None:
        self._collections = collections
        self._search_order = search_order
        self._store_routing = store_routing
        self._force = force
        self._stats = CacheStats()

    def initialize(self) -> None:
        """Scan all backends at build start.

        Local backends populate their in-memory index from disk.
        Remote backends fetch the top-level package list.
        """
        for name in self._search_order:
            if name not in self._collections:
                logger.warning("collection %r in search order but not configured", name)
                continue
            self._collections[name].scan_all()

    def lookup_wheel(
        self,
        req: Requirement,
        version: Version,
        build_tag: BuildTag,
    ) -> CacheResult:
        """Search collections in priority order for a matching wheel.

        Returns the first hit found. On a remote hit, the wheel is
        downloaded to the collection's local store backend.
        """
        if self._force:
            self._stats.record_miss(req, version, "forced")
            return CacheResult(hit=False)

        key = WheelCacheKey(
            package=canonicalize_name(req.name),
            version=version,
            build_tag=build_tag,
        )

        for collection_name in self._search_order:
            collection = self._collections.get(collection_name)
            if collection is None:
                continue

            for backend in collection.backends:
                t0 = time.monotonic()
                info = backend.lookup(key)
                if info is None:
                    continue

                # Hit -- fetch the artifact to a local path
                local_path = backend.fetch(
                    key, info, collection.store_backend.directory
                )
                duration_ms = (time.monotonic() - t0) * 1000
                was_downloaded = not backend.writable

                self._stats.record_hit(
                    req,
                    version,
                    collection_name,
                    backend.name,
                    duration_ms=duration_ms,
                )
                logger.info(
                    "cache hit for %s==%s in %s/%s",
                    req.name,
                    version,
                    collection_name,
                    backend.name,
                )
                return CacheResult(
                    hit=True,
                    path=local_path,
                    collection=collection_name,
                    backend_name=backend.name,
                    build_tag=build_tag,
                    was_downloaded=was_downloaded,
                )

        self._stats.record_miss(req, version, "not_found")
        logger.debug("cache miss for %s==%s", req.name, version)
        return CacheResult(hit=False)

    def lookup_sdist(
        self,
        req: Requirement,
        version: Version,
    ) -> CacheResult:
        """Search for a cached sdist across collections.

        Uses the same search order as wheel lookups. Sdist keys do not
        include build tags.
        """
        if self._force:
            self._stats.record_miss(req, version, "forced", artifact_type="sdist")
            return CacheResult(hit=False)

        # Sdist lookup reuses wheel key matching against .tar.gz/.zip files
        # For now, delegate to a simple filename-based check in local backends
        # TODO: extend backends with sdist-specific scan/lookup
        self._stats.record_miss(req, version, "not_implemented", artifact_type="sdist")
        return CacheResult(hit=False)

    def store_wheel(
        self,
        req: Requirement,
        version: Version,
        build_tag: BuildTag,
        wheel_path: pathlib.Path,
    ) -> pathlib.Path:
        """Route and store a newly built wheel in the appropriate collection."""
        collection_name = self._store_routing.route(req)
        collection = self._collections.get(collection_name)
        if collection is None:
            raise ValueError(
                f"store routing returned unknown collection {collection_name!r} "
                f"for {req.name}"
            )

        key = WheelCacheKey(
            package=canonicalize_name(req.name),
            version=version,
            build_tag=build_tag,
        )

        info = collection.store_backend.store(key, wheel_path)
        self._stats.record_store(req, version, collection_name)
        logger.info("stored %s in collection %r", info.filename, collection_name)
        return pathlib.Path(info.url_or_path)

    @property
    def stats(self) -> CacheStats:
        return self._stats

    @property
    def collections(self) -> dict[str, CacheCollection]:
        return self._collections

    @property
    def search_order(self) -> list[str]:
        return list(self._search_order)
