"""Unified cache subsystem for Fromager artifact management.

Provides a layered cache with prioritized multi-backend lookup. Backends
are searched in order (local directories first, then remote PEP 503
repositories). Stores always go to a single designated local backend.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import pathlib
import re
import shutil
import tempfile
import threading
import time
import typing
from html import unescape
from urllib.parse import unquote, urlparse

from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier
from packaging.utils import (
    BuildTag,
    InvalidWheelFilename,
    NormalizedName,
    canonicalize_name,
    parse_wheel_filename,
)
from packaging.version import Version

from .request_session import session
from .resolver import SUPPORTED_TAGS, match_py_req

if typing.TYPE_CHECKING:
    from . import context

logger = logging.getLogger(__name__)


def _wheel_compatible(filename: str) -> bool:
    """Return True if the wheel's tags intersect the current interpreter tags."""
    try:
        _, _, _, tags = parse_wheel_filename(filename)
    except InvalidWheelFilename:
        return False
    return bool(SUPPORTED_TAGS.intersection(tags))


# Quote-aware <a> matching so attributes like data-requires-python=">=3.8"
# do not truncate the tag at the embedded '>'.
_ANCHOR_RE = re.compile(
    r"<a\b((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_HREF_RE = re.compile(r"""\bhref\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_YANKED_RE = re.compile(r"\bdata-yanked\b", re.IGNORECASE)
_REQUIRES_PYTHON_RE = re.compile(
    r"""\bdata-requires-python\s*=\s*["']([^"']*)["']""",
    re.IGNORECASE,
)


def _iter_anchor_links(html: str) -> typing.Iterator[tuple[str, str, str]]:
    """Yield ``(href, link_text, attrs)`` triples from HTML anchor tags."""
    for match in _ANCHOR_RE.finditer(html):
        attrs, text = match.group(1), match.group(2)
        href_match = _HREF_RE.search(attrs)
        if href_match is None:
            continue
        yield href_match.group(1), re.sub(r"\s+", " ", text).strip(), attrs


# ---------------------------------------------------------------------------
# Cache Keys
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class WheelCacheKey:
    """Identifies a cached wheel artifact.

    The key uses package name, version, and build tag for precise matching.
    """

    package: NormalizedName
    version: Version
    build_tag: BuildTag  # (int, str) from changelog; () if untagged

    def __str__(self) -> str:
        tag_str = f"-{self.build_tag[0]}{self.build_tag[1]}" if self.build_tag else ""
        return f"{self.package}=={self.version}{tag_str}"


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
    """Result of a cache lookup operation.

    ``was_downloaded`` is True when the artifact came from a backend other
    than the store backend (for example build-dir or remote) and was
    registered into the store directory, so the caller should refresh the
    local wheel mirror. ``path`` always points at the store copy after
    promotion.
    """

    hit: bool
    path: pathlib.Path | None = None
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
    backend: str
    duration_ms: float | None = None


@dataclasses.dataclass
class CacheStats:
    """Accumulates cache events for a single run.

    Thread-safe: all mutations and reads of ``events`` are protected by a lock
    so background I/O threads can record hits/misses concurrently.
    """

    events: list[CacheEvent] = dataclasses.field(default_factory=list)
    _lock: threading.Lock = dataclasses.field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    def record_hit(
        self,
        req: Requirement,
        version: Version,
        backend: str,
        artifact_type: typing.Literal["wheel", "sdist"] = "wheel",
        duration_ms: float | None = None,
    ) -> None:
        event = CacheEvent(
            timestamp=time.time(),
            action="hit",
            artifact_type=artifact_type,
            package=str(req.name),
            version=str(version),
            backend=backend,
            duration_ms=duration_ms,
        )
        with self._lock:
            self.events.append(event)

    def record_miss(
        self,
        req: Requirement,
        version: Version,
        reason: str,
        artifact_type: typing.Literal["wheel", "sdist"] = "wheel",
    ) -> None:
        event = CacheEvent(
            timestamp=time.time(),
            action="miss",
            artifact_type=artifact_type,
            package=str(req.name),
            version=str(version),
            backend=reason,
        )
        with self._lock:
            self.events.append(event)

    def record_store(
        self,
        req: Requirement,
        version: Version,
        backend: str,
        artifact_type: typing.Literal["wheel", "sdist"] = "wheel",
    ) -> None:
        event = CacheEvent(
            timestamp=time.time(),
            action="store",
            artifact_type=artifact_type,
            package=str(req.name),
            version=str(version),
            backend=backend,
        )
        with self._lock:
            self.events.append(event)

    @property
    def hits(self) -> int:
        with self._lock:
            return sum(1 for e in self.events if e.action == "hit")

    @property
    def misses(self) -> int:
        with self._lock:
            return sum(1 for e in self.events if e.action == "miss")

    @property
    def stores(self) -> int:
        with self._lock:
            return sum(1 for e in self.events if e.action == "store")

    @property
    def hit_rate(self) -> float:
        with self._lock:
            hits = sum(1 for e in self.events if e.action == "hit")
            misses = sum(1 for e in self.events if e.action == "miss")
        total = hits + misses
        if total == 0:
            return 0.0
        return hits / total

    def summary(self) -> dict[str, typing.Any]:
        """Return a structured summary suitable for JSON serialization."""
        with self._lock:
            events = list(self.events)
        hits_by_backend: dict[str, int] = {}
        hits = 0
        misses = 0
        stores = 0
        for e in events:
            if e.action == "hit":
                hits += 1
                hits_by_backend[e.backend] = hits_by_backend.get(e.backend, 0) + 1
            elif e.action == "miss":
                misses += 1
            elif e.action == "store":
                stores += 1
        total = hits + misses
        return {
            "hits": {
                "total": hits,
                "by_backend": hits_by_backend,
            },
            "misses": misses,
            "stores": stores,
            "hit_rate": round(hits / total, 4) if total else 0.0,
        }


# ---------------------------------------------------------------------------
# Cache Backend Protocol
# ---------------------------------------------------------------------------


class CacheBackend(typing.Protocol):
    """Protocol for a single storage location that can find and store artifacts."""

    @property
    def name(self) -> str:
        """Human-readable identifier (e.g., 'local:downloads', 'remote:https://...')."""
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

    def items(self) -> typing.Iterable[tuple[WheelCacheKey, ArtifactInfo]]:
        """Iterate over all indexed artifacts in this backend."""
        ...


# ---------------------------------------------------------------------------
# Local Directory Backend
# ---------------------------------------------------------------------------


class LocalDirectoryBackend:
    """Cache backend backed by a local filesystem directory.

    Scans at startup to populate an in-memory index from existing wheel files.
    New stores are reflected immediately in the index. All public methods are
    thread-safe.
    """

    def __init__(
        self,
        directory: pathlib.Path,
        backend_name: str = "local",
        *,
        recursive: bool = False,
    ) -> None:
        self._directory = directory
        self._backend_name = backend_name
        self._recursive = recursive
        self._index: dict[WheelCacheKey, ArtifactInfo] = {}
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._backend_name

    @property
    def writable(self) -> bool:
        return True

    @property
    def directory(self) -> pathlib.Path:
        return self._directory

    def _iter_wheel_files(self) -> typing.Iterator[pathlib.Path]:
        """Yield wheel files in this backend's directory."""
        yield from self._directory.glob("*.whl")
        if self._recursive:
            # Parallel builds land wheels in wheels_build_base/<thread_id>/.
            yield from self._directory.glob("*/*.whl")

    def scan(self) -> dict[WheelCacheKey, ArtifactInfo]:
        """Scan the directory for wheel files and populate the index.

        Only indexes wheels compatible with the current interpreter tags.
        """
        with self._lock:
            self._index.clear()
            if not self._directory.exists():
                return dict(self._index)

            for wheel_file in self._iter_wheel_files():
                if wheel_file.is_symlink():
                    continue
                if not _wheel_compatible(wheel_file.name):
                    logger.debug(
                        "skipping incompatible wheel for this platform: %s",
                        wheel_file.name,
                    )
                    continue
                try:
                    name, version, build_tag, _ = parse_wheel_filename(wheel_file.name)
                    key = WheelCacheKey(
                        package=name,
                        version=version,
                        build_tag=build_tag,
                    )
                    # Keep the first compatible wheel for a key.
                    if key in self._index:
                        continue
                    info = ArtifactInfo(
                        filename=wheel_file.name,
                        url_or_path=str(wheel_file.resolve()),
                        size_bytes=wheel_file.stat().st_size,
                    )
                    self._index[key] = info
                except InvalidWheelFilename:
                    logger.debug("skipping unparseable wheel file: %s", wheel_file.name)
            logger.debug("scanned %d wheels in %s", len(self._index), self._directory)
            return dict(self._index)

    def lookup(self, key: WheelCacheKey) -> ArtifactInfo | None:
        """Look up artifact in the in-memory index.

        When ``key.build_tag`` is empty, matches any build tag for the same
        package+version (legacy ``find_wheel`` semantics). Prefers the highest
        build tag number when multiple candidates exist. Only returns wheels
        compatible with the current interpreter tags.
        """
        with self._lock:
            if key.build_tag:
                info = self._index.get(key)
                if info is None:
                    return None
                file_path = pathlib.Path(info.url_or_path)
                if not file_path.exists():
                    del self._index[key]
                    return None
                if not _wheel_compatible(info.filename):
                    return None
                return info

            # Empty build tag: accept any matching package+version.
            candidates: list[tuple[WheelCacheKey, ArtifactInfo]] = []
            stale: list[WheelCacheKey] = []
            for indexed_key, info in self._index.items():
                if (
                    indexed_key.package != key.package
                    or indexed_key.version != key.version
                ):
                    continue
                if not pathlib.Path(info.url_or_path).exists():
                    stale.append(indexed_key)
                    continue
                if not _wheel_compatible(info.filename):
                    continue
                candidates.append((indexed_key, info))
            for stale_key in stale:
                del self._index[stale_key]
            if not candidates:
                return None
            candidates.sort(
                key=lambda item: item[0].build_tag[0] if item[0].build_tag else -1,
                reverse=True,
            )
            return candidates[0][1]

    def fetch(
        self, key: WheelCacheKey, info: ArtifactInfo, dest: pathlib.Path
    ) -> pathlib.Path:
        """Return the existing local path (no-op for local backends)."""
        return pathlib.Path(info.url_or_path)

    def store(self, key: WheelCacheKey, artifact: pathlib.Path) -> ArtifactInfo:
        """Register an artifact in this backend's directory.

        If the artifact is not already in the directory, it is atomically
        copied there (preserving the original for the internal wheel server
        index). Updates the in-memory index.
        """
        dest = self._directory / artifact.name
        self._directory.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or not artifact.samefile(dest):
            fd = tempfile.NamedTemporaryFile(
                dir=self._directory,
                prefix=f".{dest.name}.",
                suffix=".tmp",
                delete=False,
            )
            tmp_dest = pathlib.Path(fd.name)
            fd.close()
            try:
                shutil.copy2(str(artifact), str(tmp_dest))
                tmp_dest.replace(dest)
            except BaseException:
                tmp_dest.unlink(missing_ok=True)
                raise

        info = ArtifactInfo(
            filename=dest.name,
            url_or_path=str(dest.resolve()),
            size_bytes=dest.stat().st_size,
        )
        with self._lock:
            self._index[key] = info
        return info

    def items(self) -> typing.Iterable[tuple[WheelCacheKey, ArtifactInfo]]:
        """Iterate over all indexed artifacts."""
        with self._lock:
            return list(self._index.items())


# ---------------------------------------------------------------------------
# Remote PEP 503 Backend
# ---------------------------------------------------------------------------


class RemotePEP503Backend:
    """Cache backend backed by a remote PEP 503 (Simple Repository API) server.

    At startup, fetches the top-level package list. Individual project pages
    are fetched lazily on first lookup per package and memoized for the run.
    All public methods are thread-safe.
    """

    def __init__(
        self,
        server_url: str,
        download_dir: pathlib.Path,
        backend_name: str | None = None,
        allow_insecure: bool = False,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._download_dir = download_dir
        self._backend_name = backend_name or f"remote:{self._server_url}"
        self._allow_insecure = allow_insecure
        self._available_packages: set[NormalizedName] | None = None
        self._project_cache: dict[NormalizedName, list[ArtifactInfo]] = {}
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._backend_name

    @property
    def writable(self) -> bool:
        return False

    def scan(self) -> dict[WheelCacheKey, ArtifactInfo]:
        """Fetch top-level index to learn which packages exist.

        On index fetch failure, ``_available_packages`` stays ``None`` so
        lookups still attempt per-project pages instead of treating every
        package as unknown.
        """
        self._available_packages = self._fetch_package_list()
        if self._available_packages is None:
            logger.warning(
                "remote index %s unavailable; will probe project pages lazily",
                self._server_url,
            )
        else:
            logger.debug(
                "remote %s has %d packages available",
                self._server_url,
                len(self._available_packages),
            )
        return {}

    def lookup(self, key: WheelCacheKey) -> ArtifactInfo | None:
        """Lazy per-package lookup with short-circuit for unknown packages.

        Only returns wheels compatible with the current interpreter tags.
        Transient project-page failures are not memoized.
        """
        if (
            self._available_packages is not None
            and key.package not in self._available_packages
        ):
            return None

        # Double-checked locking: never hold the lock during network I/O so
        # concurrent lookups for other packages are not blocked.
        with self._lock:
            cached = self._project_cache.get(key.package)
        if cached is None:
            fetched = self._fetch_project_page(key.package)
            if fetched is None:
                # Transient failure — do not memoize; try again next lookup.
                return None
            with self._lock:
                # Another thread may have filled the cache while we fetched.
                cached = self._project_cache.setdefault(key.package, fetched)

        matches: list[tuple[BuildTag, ArtifactInfo]] = []
        for info in cached:
            try:
                name, version, build_tag, _ = parse_wheel_filename(info.filename)
            except InvalidWheelFilename:
                continue
            if name != key.package or version != key.version:
                continue
            if not _wheel_compatible(info.filename):
                continue
            if key.build_tag and build_tag != key.build_tag:
                continue
            if key.build_tag:
                return info
            matches.append((build_tag, info))

        if not matches:
            return None
        # Empty expected build tag: prefer highest available build tag.
        matches.sort(key=lambda item: item[0][0] if item[0] else -1, reverse=True)
        return matches[0][1]

    def fetch(
        self, key: WheelCacheKey, info: ArtifactInfo, dest: pathlib.Path
    ) -> pathlib.Path:
        """Download the wheel from the remote server with SHA256 verification."""
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / info.filename

        if target.exists():
            if info.sha256:
                verify_hash = hashlib.sha256()
                with open(target, "rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        verify_hash.update(chunk)
                if verify_hash.hexdigest().lower() == info.sha256.lower():
                    return target
                logger.warning(
                    "existing %s has wrong sha256, re-downloading", info.filename
                )
                target.unlink()
            else:
                return target

        url = info.url_or_path
        logger.info(
            "downloading cached wheel %s from %s", info.filename, self._server_url
        )
        resp = session.get(url, stream=True)
        resp.raise_for_status()
        hasher = hashlib.sha256() if info.sha256 else None
        fd = tempfile.NamedTemporaryFile(
            dir=dest,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        )
        tmp_target = pathlib.Path(fd.name)
        fd.close()
        try:
            with open(tmp_target, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    if hasher is not None:
                        hasher.update(chunk)
                    f.write(chunk)
            expected_sha256 = info.sha256
            if (
                hasher is not None
                and expected_sha256 is not None
                and hasher.hexdigest().lower() != expected_sha256.lower()
            ):
                raise ValueError(
                    f"sha256 mismatch for {info.filename}: "
                    f"expected {expected_sha256}, got {hasher.hexdigest()}"
                )
            tmp_target.replace(target)
        except BaseException:
            tmp_target.unlink(missing_ok=True)
            raise
        return target

    def store(self, key: WheelCacheKey, artifact: pathlib.Path) -> ArtifactInfo:
        """Not supported for remote backends."""
        raise NotImplementedError("Remote backends are read-only")

    def items(self) -> typing.Iterable[tuple[WheelCacheKey, ArtifactInfo]]:
        """Iterate over cached project page data (may be incomplete)."""
        with self._lock:
            results: list[tuple[WheelCacheKey, ArtifactInfo]] = []
            for artifacts in self._project_cache.values():
                for info in artifacts:
                    try:
                        name, version, build_tag, _ = parse_wheel_filename(
                            info.filename
                        )
                        key = WheelCacheKey(
                            package=name, version=version, build_tag=build_tag
                        )
                        results.append((key, info))
                    except InvalidWheelFilename:
                        continue
            return results

    def _fetch_package_list(self) -> set[NormalizedName] | None:
        """Fetch the top-level /simple/ index and extract package names.

        Returns an empty set for definitive "no packages" responses (HTTP 400/404
        or a successful empty page). Returns ``None`` for transport/5xx failures
        so callers can still fall back to lazy project-page probes.
        """
        url = f"{self._server_url}/"
        try:
            resp = session.get(url)
        except Exception as err:
            logger.warning("failed to fetch remote index %s: %s", url, err)
            return None

        if resp.status_code in {400, 404}:
            logger.warning(
                "remote index %s returned %s; treating as empty for this run",
                url,
                resp.status_code,
            )
            return set()

        try:
            resp.raise_for_status()
        except Exception as err:
            logger.warning("failed to fetch remote index %s: %s", url, err)
            return None

        return self._parse_index_page(resp.text)

    def _fetch_project_page(self, package: NormalizedName) -> list[ArtifactInfo] | None:
        """Fetch a project's page and extract wheel artifact info.

        Returns an empty list for definitive misses (HTTP 400/404 or a
        successful page with no usable wheels) so callers can memoize the
        negative result for the run. Returns ``None`` for transport/5xx
        failures (not memoized; retried on later lookups).
        """
        url = f"{self._server_url}/{package}/"
        try:
            resp = session.get(url)
        except Exception as err:
            logger.debug("failed to fetch project page %s: %s", url, err)
            return None

        if resp.status_code in {400, 404}:
            logger.debug(
                "project page %s returned %s; treating as empty for this run",
                url,
                resp.status_code,
            )
            return []

        try:
            resp.raise_for_status()
        except Exception as err:
            logger.debug("failed to fetch project page %s: %s", url, err)
            return None

        return self._parse_project_page(resp.text, url, self._allow_insecure)

    @staticmethod
    def _parse_index_page(html: str) -> set[NormalizedName]:
        """Extract package names from a PEP 503 index page."""
        names: set[NormalizedName] = set()
        for _href, text, _attrs in _iter_anchor_links(html):
            name = text.rstrip("/")
            if name:
                names.add(canonicalize_name(name))
        return names

    @staticmethod
    def _parse_project_page(
        html: str, base_url: str, allow_insecure: bool = False
    ) -> list[ArtifactInfo]:
        """Extract wheel artifact info from a PEP 503 project page.

        Skips yanked files (PEP 592) and wheels whose ``data-requires-python``
        does not match the current interpreter, matching resolver behavior.
        """
        artifacts: list[ArtifactInfo] = []
        for href, filename, attrs in _iter_anchor_links(html):
            # Simple indexes (including Fromager's) percent-encode filenames
            # in link text/hrefs (e.g. local versions with '+').
            filename = unquote(filename)
            if not filename.endswith(".whl"):
                continue

            if _YANKED_RE.search(attrs):
                logger.debug("skipping yanked remote artifact %r", filename)
                continue

            requires_python_match = _REQUIRES_PYTHON_RE.search(attrs)
            if requires_python_match:
                # Warehouse escapes attribute values (e.g. "&gt;=3.8").
                requires_python = unescape(requires_python_match.group(1))
                try:
                    if not match_py_req(requires_python):
                        logger.debug(
                            "skipping remote artifact %r due to requires-python %r",
                            filename,
                            requires_python,
                        )
                        continue
                except InvalidSpecifier:
                    logger.debug(
                        "skipping remote artifact %r due to invalid requires-python %r",
                        filename,
                        requires_python,
                    )
                    continue

            # Reject filenames with path components to prevent directory traversal
            safe_filename = pathlib.PurePosixPath(filename).name
            if safe_filename != filename:
                logger.warning(
                    "skipping remote artifact with unsafe filename %r", filename
                )
                continue
            filename = safe_filename

            # Resolve relative URLs (schemes are case-insensitive per RFC 3986).
            href_scheme = urlparse(href).scheme.lower()
            if href_scheme in {"http", "https"}:
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
                if fragment.lower().startswith("sha256="):
                    sha256 = fragment.split("=", 1)[1]
                url = url_part

            # Reject plaintext HTTP URLs that lack integrity metadata
            if (
                urlparse(url).scheme.lower() == "http"
                and not sha256
                and not allow_insecure
            ):
                logger.warning(
                    "skipping insecure artifact %r (http without sha256)", filename
                )
                continue

            artifacts.append(
                ArtifactInfo(
                    filename=filename,
                    url_or_path=url,
                    sha256=sha256,
                )
            )
        return artifacts


# ---------------------------------------------------------------------------
# Cache Manager
# ---------------------------------------------------------------------------


class CacheManager:
    """Unified entry point for all cache operations.

    Searches multiple backends in priority order for lookups. Stores always
    go to a single designated local backend.
    """

    def __init__(
        self,
        lookup_backends: list[CacheBackend],
        store_backend: LocalDirectoryBackend,
        force: bool = False,
    ) -> None:
        self._lookup_backends = lookup_backends
        self._store_backend = store_backend
        self._force = force
        self._stats = CacheStats()

    @property
    def lookup_backends(self) -> list[CacheBackend]:
        """Ordered list of backends searched during lookups."""
        return list(self._lookup_backends)

    @property
    def store_backend(self) -> LocalDirectoryBackend:
        """The single backend that receives stored artifacts."""
        return self._store_backend

    def initialize(self) -> None:
        """Scan all backends at build start.

        Local backends populate their in-memory index from disk.
        Remote backends fetch the top-level package list.
        """
        for backend in self._lookup_backends:
            backend.scan()

    def lookup_wheel(
        self,
        req: Requirement,
        version: Version,
        build_tag: BuildTag,
    ) -> CacheResult:
        """Search backends in priority order for a matching wheel.

        Returns the first hit found. On a remote hit, the wheel is
        downloaded to the store backend's directory.
        """
        if self._force:
            self._stats.record_miss(req, version, "forced")
            return CacheResult(hit=False)

        key = WheelCacheKey(
            package=canonicalize_name(req.name),
            version=version,
            build_tag=build_tag,
        )

        for backend in self._lookup_backends:
            t0 = time.monotonic()
            info = backend.lookup(key)
            if info is None:
                continue

            # Hit -- fetch the artifact to a local path
            try:
                local_path = backend.fetch(key, info, self._store_backend.directory)
                # Register in the store index so subsequent lookups
                # find it locally without hitting the remote again.
                # was_downloaded means "came from a non-store backend" so the
                # caller knows the local mirror may need updating.
                was_downloaded = backend is not self._store_backend
                if was_downloaded:
                    stored = self._store_backend.store(key, local_path)
                    local_path = pathlib.Path(stored.url_or_path)
            except Exception as err:
                logger.warning(
                    "cache hit for %s==%s in %s could not be fetched: %s",
                    req.name,
                    version,
                    backend.name,
                    err,
                )
                continue
            duration_ms = (time.monotonic() - t0) * 1000

            self._stats.record_hit(
                req,
                version,
                backend.name,
                duration_ms=duration_ms,
            )
            logger.info(
                "cache hit for %s==%s in %s",
                req.name,
                version,
                backend.name,
            )
            result_build_tag = build_tag
            if not result_build_tag:
                try:
                    _, _, parsed_tag, _ = parse_wheel_filename(local_path.name)
                    result_build_tag = parsed_tag
                except InvalidWheelFilename:
                    pass
            return CacheResult(
                hit=True,
                path=local_path,
                backend_name=backend.name,
                build_tag=result_build_tag,
                was_downloaded=was_downloaded,
            )

        self._stats.record_miss(req, version, "not_found")
        logger.debug("cache miss for %s==%s", req.name, version)
        return CacheResult(hit=False)

    def store_wheel(
        self,
        req: Requirement,
        version: Version,
        build_tag: BuildTag,
        wheel_path: pathlib.Path,
    ) -> pathlib.Path:
        """Store a newly built wheel in the store backend.

        When ``build_tag`` is empty, derive it from the wheel filename so the
        index key matches what ``scan()`` would produce.
        """
        if not build_tag:
            try:
                _, _, parsed_tag, _ = parse_wheel_filename(wheel_path.name)
                build_tag = parsed_tag
            except InvalidWheelFilename:
                pass

        key = WheelCacheKey(
            package=canonicalize_name(req.name),
            version=version,
            build_tag=build_tag,
        )

        info = self._store_backend.store(key, wheel_path)
        self._stats.record_store(req, version, self._store_backend.name)
        logger.info("stored %s in %s", info.filename, self._store_backend.name)
        return pathlib.Path(info.url_or_path)

    @property
    def stats(self) -> CacheStats:
        """Cache statistics for the current run."""
        return self._stats


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_cache_manager(
    wkctx: context.WorkContext,
    cache_url: str | None = None,
    allow_insecure: bool = False,
) -> CacheManager:
    """Construct a CacheManager from the WorkContext configuration.

    If the context already has a cache configured, return it.
    Otherwise, build one from the standard filesystem layout.

    Lookup order (matches legacy ``find_cached_wheel``):
    1. ``wheels_build`` (freshly built, not yet mirrored; scanned recursively
       for parallel-build thread subdirectories)
    2. ``wheels_downloads`` (previously downloaded/built wheels)
    3. Remote PEP 503 server (if ``cache_url`` is provided)

    ``wheels_prebuilt`` is intentionally omitted: prebuilt packages use the
    dedicated prebuilt bootstrap path (``SourceType.PREBUILT``), not the
    general cache short-circuit.

    Store destination: ``wheels_downloads``.

    Args:
        wkctx: The work context providing local paths.
        cache_url: Optional URL to a remote PEP 503 cache server.
        allow_insecure: Allow HTTP URLs without SHA256 hashes.
    """
    if wkctx.cache is not None:
        return wkctx.cache

    # Match legacy find_cached_wheel order: build dir, downloads, then remote.
    # Use wheels_build_base (not the thread-local wheels_build property) so the
    # index is shared across threads. recursive=True covers parallel-build
    # subdirectories under wheels_build_base/<native_id>/.
    build_backend = LocalDirectoryBackend(
        wkctx.wheels_build_base,
        backend_name="local:build",
        recursive=True,
    )
    downloads_backend = LocalDirectoryBackend(
        wkctx.wheels_downloads, backend_name="local:downloads"
    )

    lookup_backends: list[CacheBackend] = [
        build_backend,
        downloads_backend,
    ]

    if cache_url:
        remote_backend = RemotePEP503Backend(
            server_url=cache_url,
            download_dir=wkctx.wheels_downloads,
            backend_name=f"remote:{cache_url}",
            allow_insecure=allow_insecure,
        )
        lookup_backends.append(remote_backend)

    manager = CacheManager(
        lookup_backends=lookup_backends,
        store_backend=downloads_backend,
    )
    manager.initialize()
    wkctx.cache = manager
    return manager
