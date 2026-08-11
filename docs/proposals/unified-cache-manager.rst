Proposal: Unified Cache Manager
================================

Problem
-------

Fromager's caching logic is scattered across multiple modules with no central
coordination. Prebuilt wheels are checked separately from previously built
wheels, remote wheel servers are not consulted during local builds, and there
is no mechanism to share a cache across multiple backends. This leads to:

- Redundant builds when wheels already exist in a remote cache.
- No visibility into cache hit rates, artifact integrity, or staleness.
- No short-circuit path — even a full cache hit still downloads source and
  sets up a build environment before discovering the wheel exists.

Proposed Solution
-----------------

Introduce a unified ``CacheManager`` class that centralizes all cache
operations behind a prioritized multi-backend lookup strategy.

Architecture
~~~~~~~~~~~~

.. code-block:: text

   CacheManager
   ├── lookup_backends (searched in order):
   │   ├── LocalDirectoryBackend(wheels-repo/build/)   [recursive for parallel builds]
   │   ├── LocalDirectoryBackend(wheels-repo/downloads/)
   │   └── RemotePEP503Backend(https://cache-server/simple/)  [optional]
   └── store_backend:
       └── LocalDirectoryBackend(wheels-repo/downloads/)

   Prebuilt wheels stay on the dedicated ``SourceType.PREBUILT`` path and are
   not consulted by the general cache short-circuit.

Key components:

- ``WheelCacheKey`` — Content-addresses artifacts by canonicalized package
  name, version, and numeric build tag. Wheel compatibility tags
  (interpreter, ABI, platform) are not part of the key; instead, backends
  filter candidates against the current interpreter's supported tags at
  lookup time, keeping the key space small while ensuring only compatible
  wheels are returned.
- ``CacheBackend`` protocol — Abstract interface implemented by
  ``LocalDirectoryBackend`` (filesystem) and ``RemotePEP503Backend``
  (PEP 503 simple repository). Thread-safe with internal locking.
- ``CacheManager`` — Orchestrates prioritized lookup across backends with
  graceful fallback on fetch failures, and routes all stores to a single
  designated local backend.

Lookup and store
~~~~~~~~~~~~~~~~

On lookup, the manager iterates ``lookup_backends`` in order and returns the
first hit. Remote hits are downloaded to the store backend's directory and
registered in the local index for subsequent fast lookups.

On store, newly built wheels are always placed in the single ``store_backend``
(the downloads directory). This keeps the design simple and avoids
collection-routing complexity in core Fromager. Variant-specific routing
can be added as builder-level logic in a follow-up.

Short-circuit optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~

When a cache hit is found during the ``PREPARE_SOURCE`` phase and a
``CacheManager`` is active, ``PrepareSource.run()`` skips build environment
creation and build dependency resolution entirely — proceeding directly to
``ProcessInstallDeps``. Install dependencies are extracted from the cached
wheel's metadata. This eliminates the most expensive steps for packages that
do not need rebuilding.

Remote cache with integrity
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``RemotePEP503Backend`` lazily fetches per-project package indices on first
access and maintains a session-scoped in-memory index. Lookups honor
interpreter wheel tags, skip yanked files (PEP 592), and filter
``data-requires-python`` the same way the resolver does. Downloads are
verified with streaming SHA256 checksums, use atomic temporary files, and
reject plaintext HTTP URLs that lack integrity hashes (unless
``--cache-allow-insecure`` is passed for development workflows). Filenames
are sanitized to prevent path traversal attacks. HTTP 400/404 (and empty
successful pages) are treated as definitive misses for the run; transport
and 5xx failures are retried on later lookups.

Observability
~~~~~~~~~~~~~

A new ``fromager cache`` CLI command group provides:

- ``cache list`` — Show all cached artifacts with versions and build tags.
- ``cache stats`` — Display on-disk inventory counts and sizes per backend.
  (Hit/miss rates are process-local during bootstrap and are not persisted.)
- ``cache verify`` — Validate integrity of local cache contents.
- ``cache invalidate`` — Remove specific artifacts by name/version/tag.
- ``cache gc`` — Garbage-collect old build tags, keeping only the N most
  recent per package+version.

Scope
-----

The new cache subsystem is opt-in via ``--use-cache-manager`` on the
``bootstrap`` command. When disabled, existing behavior is preserved
unchanged.

Planned implementation touchpoints:

- ``src/fromager/cache.py`` — New module with all cache classes and factory.
- ``src/fromager/commands/cache_cmd.py`` — CLI commands.
- ``src/fromager/commands/bootstrap.py`` — Wiring ``--use-cache-manager`` and
  ``--cache-allow-insecure`` options.
- ``src/fromager/bootstrapper/_cache.py`` — Short-circuit integration via
  ``_find_cached_wheel_via_manager``.
- ``src/fromager/context.py`` — ``cache`` property on ``WorkContext``.
- ``tests/test_cache.py`` — Unit tests for the cache subsystem.

Benefits
--------

- Eliminates redundant builds when wheels exist in a remote or local cache.
- Reduces bootstrap time by short-circuiting cached packages (skips source
  download, build env setup, and build dep resolution).
- Provides cache observability through dedicated CLI commands.
- Enforces artifact integrity with SHA256 verification and atomic writes.
- Thread-safe design compatible with background I/O pre-fetching.

Security considerations
-----------------------

- Remote downloads are verified against SHA256 hashes declared in PEP 503
  index pages. At the backend layer, mismatched files are deleted and a
  ``ValueError`` is raised — the corrupted artifact is never persisted.
- At the manager layer, any backend fetch failure (including hash mismatches)
  is caught and treated as a backend-level miss, falling through to the next
  backend or ultimately a fresh build. This two-layer design ensures
  integrity enforcement within each backend while providing graceful
  degradation across backends.
- Plaintext HTTP URLs without SHA256 hashes are rejected by default.
  The ``--cache-allow-insecure`` flag explicitly opts in for internal or
  development registries.
- Filenames from remote indices are sanitized to prevent directory traversal.
- Local cache writes use atomic ``tempfile`` + ``rename`` to prevent readers
  from observing partial files.
- ``scan()`` skips symlinked wheels to prevent ``invalidate``/``gc`` from
  deleting files outside the cache root.

Verification
------------

- All existing unit and e2e tests pass unchanged (legacy path preserved).
- New tests cover cache components, short-circuit logic, concurrency safety,
  CLI commands, and error handling.
- Linting (``ruff``), type checking (``mypy``), and formatting all pass.

Future work
-----------

- Integration with ``build_tag_hook`` (issue #1059) for platform-suffixed
  cache keys.
- Variant/collection-based store routing as builder-level logic (separate PR).
- Automatic detection of accelerated packages via ELF inspection or wheel
  tag analysis.
- Promotion of ``--use-cache-manager`` to default behavior once proven in
  production.
