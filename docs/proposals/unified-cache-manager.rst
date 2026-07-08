Proposal: Unified Cache Manager
================================

Problem
-------

Fromager's caching logic is scattered across multiple modules with no central
coordination. Prebuilt wheels are checked separately from previously built
wheels, remote wheel servers are not consulted during local builds, and there
is no mechanism to share a base cache of common dependencies across
hardware-specific bootstrap variants (e.g. CUDA, Gaudi). This leads to:

- Redundant builds when wheels already exist in a remote cache or sibling
  variant's output.
- Duplicated storage of common (non-accelerated) dependencies in every
  variant's output directory.
- No visibility into cache hit rates, artifact integrity, or staleness.
- No short-circuit path — even a full cache hit still downloads source and
  sets up a build environment before discovering the wheel exists.

Proposed Solution
-----------------

Introduce a unified ``CacheManager`` class that centralizes all cache
operations behind a layered lookup strategy:

Architecture
~~~~~~~~~~~~

.. code-block:: text

   CacheManager
   ├── CacheCollection("default")
   │   ├── LocalDirectoryBackend(wheels-repo/downloads/)
   │   ├── LocalDirectoryBackend(wheels-repo/prebuilt/)
   │   └── RemotePEP503Backend(https://cache-server/simple/)  [optional]
   └── CacheCollection("gaudi-ubi9")  [variant, if active]
       └── LocalDirectoryBackend(wheels-repo-gaudi-ubi9/downloads/)

Key components:

- ``WheelCacheKey`` — Content-addresses artifacts by canonicalized package
  name, version, and numeric build tag.
- ``CacheBackend`` protocol — Abstract interface implemented by
  ``LocalDirectoryBackend`` (filesystem) and ``RemotePEP503Backend``
  (PEP 503 simple repository).
- ``CacheCollection`` — Named group of backends searched in priority order
  (e.g. "default" searches local then remote).
- ``StoreRouter`` — Determines which collection owns a given package based on
  the variant's top-level requirements file and optional overrides.
- ``CacheManager`` — Orchestrates hierarchical lookup across collections with
  fallback from variant to default.

Lookup and store routing
~~~~~~~~~~~~~~~~~~~~~~~~

On lookup, the manager searches the active variant collection first, then
falls back to the default collection. Within each collection, backends are
queried in registration order (local before remote).

On store, the ``StoreRouter`` routes packages explicitly listed in the
variant's ``requirements.txt`` to the variant collection directory. All
unlisted transitive dependencies are stored in the default collection. This
prevents duplication of common packages across variant outputs.

Short-circuit optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~

When a cache hit is found during the ``PREPARE_SOURCE`` phase, the
bootstrapper skips source download, build environment creation, and build
dependency resolution entirely — proceeding directly to install dependency
extraction from the cached wheel's metadata. This eliminates the most
expensive steps for packages that do not need rebuilding.

Remote cache with integrity
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``RemotePEP503Backend`` lazily fetches per-project package indices on first
access and maintains a session-scoped in-memory index. Downloads are verified
with streaming SHA256 checksums, use atomic temporary files, and reject
plaintext HTTP URLs that lack integrity hashes (unless ``--cache-allow-insecure``
is passed for development workflows). Filenames are sanitized to prevent path
traversal attacks.

Observability
~~~~~~~~~~~~~

A new ``fromager cache`` CLI command group provides:

- ``cache list`` — Show all cached artifacts with versions and build tags.
- ``cache stats`` — Display hit/miss counts and rates from the last run.
- ``cache verify`` — Validate integrity of local cache contents.
- ``cache invalidate`` — Remove specific artifacts by name/version/tag.
- ``cache gc`` — Garbage-collect old build tags, keeping only the N most
  recent per package+version.

Scope
-----

The new cache subsystem is opt-in via ``--use-cache-manager`` on the
``bootstrap`` command. When disabled, existing behavior is preserved
unchanged.

Files added or modified:

- ``src/fromager/cache.py`` — New module with all cache classes.
- ``src/fromager/commands/cache_cmd.py`` — CLI commands and factory function.
- ``src/fromager/commands/bootstrap.py`` — Wiring ``--use-cache-manager`` and
  ``--cache-allow-insecure`` options.
- ``src/fromager/bootstrapper.py`` — Short-circuit path and store routing for
  built wheels.
- ``src/fromager/context.py`` — ``cache`` property on ``WorkContext``.
- ``src/fromager/requirements_file.py`` — ``CACHED`` source type.
- ``tests/test_cache.py`` — Unit tests for the cache subsystem.
- ``tests/test_bootstrapper_iterative.py`` — Integration tests for cache
  dispatch and store routing.

Benefits
--------

- Eliminates redundant builds when wheels exist in a remote or sibling cache.
- Reduces bootstrap time by short-circuiting cached packages (skips source
  download, build env setup, and build dep resolution).
- Prevents duplication of common dependencies across variant outputs via
  hierarchical store routing.
- Provides cache observability through dedicated CLI commands.
- Enforces artifact integrity with SHA256 verification and atomic writes.

Security considerations
-----------------------

- Remote downloads are verified against SHA256 hashes declared in PEP 503
  index pages. Mismatched files are deleted and raise an error.
- Plaintext HTTP URLs without SHA256 hashes are rejected by default.
  The ``--cache-allow-insecure`` flag explicitly opts in for internal or
  development registries.
- Filenames from remote indices are sanitized to prevent directory traversal.
- Local cache writes use atomic ``tempfile`` + ``rename`` to prevent readers
  from observing partial files.
- ``scan()`` skips symlinked wheels to prevent ``invalidate``/``gc`` from
  deleting files outside the cache root.
- Fetch failures (network errors, hash mismatches) are caught and treated as
  cache misses, falling through to the next backend or a fresh build.

Verification
------------

- All existing unit and e2e tests pass unchanged (legacy path preserved).
- 169 new tests cover cache components, short-circuit logic, store routing,
  and error handling.
- Validated on walkerpass4 with both local and remote caches:
  pre-populated local cache achieves full hit rate; remote PEP 503 server
  correctly populates local cache and only uncached packages trigger builds.
- Linting (``ruff``), type checking (``mypy``), and formatting all pass.

Future work
-----------

- Integration with ``build_tag_hook`` (issue #1059) for platform-suffixed
  cache keys.
- Automatic detection of accelerated packages via ELF inspection or wheel
  tag analysis.
- Promotion of ``--use-cache-manager`` to default behavior once proven in
  production.
