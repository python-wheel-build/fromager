Resolver Architecture
=====================

Fromager resolves package versions from multiple sources using a
provider abstraction.  This document describes the resolution
strategies, filtering, and key design decisions.

.. seealso::

   :doc:`architecture-overview` maps the major subsystems.
   :doc:`bootstrapper-architecture` covers how resolution fits into the
   bootstrap pipeline.

Resolution Strategies
---------------------

During bootstrap, the resolver coordinator tries these sources in
priority order and accumulates results in a thread-safe session cache:

.. code-block:: text

   ┌───────────────────────────────────────────────────────┐
   │               Resolution Priority Order               │
   │                                                       │
   │  1. Session cache (versions found earlier)            │
   │          │ miss                                       │
   │          ▼                                            │
   │  2. Previous dependency graph (prior run)             │
   │          │ miss                                       │
   │          ▼                                            │
   │  3. Network (PyPI / GitHub / GitLab)                  │
   │     (per-package configurable)                        │
   └───────────────────────────────────────────────────────┘

   Git URL requirements (top-level only) bypass this
   chain entirely: the repo is cloned and the version
   is extracted from package metadata.

Versions discovered from any source are merged into the session cache.
Subsequent requests for the same package skip the network entirely if
the cache already contains a matching version.

The configured wheel cache server is not a version-resolution fallback.
After a version has been selected, the bootstrapper checks the cache
server separately for a previously built wheel.
For prebuilt packages, the local wheel server can supply a cached wheel
before a fresh resolution through the selected source provider.

Provider Hierarchy
------------------

All resolution sources inherit from ``BaseProvider``, which implements
the resolvelib ``ExtrasProvider`` interface.  The bootstrap engine and
CLI commands interact with providers through a common
``find_matches()`` method.

.. code-block:: text

   BaseProvider
   ├── PyPIProvider         (PEP 503 Simple API)
   │   └── PyPICacheProvider  (fromager's own wheel server)
   ├── GenericProvider      (callback-based, parses tags)
   │   ├── GitHubTagProvider
   │   └── GitLabTagProvider
   └── VersionMapProvider   (pre-resolved version→URL map)

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Provider
     - What it queries
   * - ``PyPIProvider``
     - Any PEP 503 Simple API index (pypi.org, custom mirrors).
       Filters by platform tags, Python version, and yanked status.
   * - ``PyPICacheProvider``
     - Subclass of ``PyPIProvider`` pointing at fromager's own wheel
       server.  No cooldown applied.  Used by the bootstrapper's
       previously-built-wheel lookup, not by source version resolution.
   * - ``GenericProvider``
     - Callback-based provider that pairs a version source function
       with a configurable match function (plain parse or regex).
       Base class for the tag providers below.
   * - ``GitHubTagProvider``
     - GitHub REST API for repository tags.  Versions are parsed
       from tag names using a configurable pattern.
   * - ``GitLabTagProvider``
     - GitLab REST API for repository tags.  Includes upload
       timestamps for age filtering.
   * - ``VersionMapProvider``
     - Wraps a pre-built ``VersionMap`` (version → URL mapping).
       Used when versions are already known, e.g. from a prior
       resolution or a settings-provided URL template.

.. versionchanged:: 0.95.0
   Packages with ``source:`` configuration now select their provider through
   the configured source resolver.

.. versionchanged:: 0.96.0
   The ``hook-sdist`` and ``hook-prebuilt`` profiles create providers through
   the required ``get_resolver_provider`` override hook. They do not fall back
   to PyPI. Their ``download()`` methods invoke the package's ``download_source``
   hook when present and return a validated ``DownloadedSource``.

.. versionchanged:: 0.102.0
   Configured source resolvers own their index URL and ignore caller URLs.
   Hook profiles pass their ``index_url`` to the legacy
   ``get_resolver_provider`` hook as ``sdist_server_url``. ``hook-sdist``
   defaults to PyPI, while ``hook-prebuilt`` requires an explicit index.

Per-package settings in YAML can select which provider to use and
configure its parameters (index URL, tag pattern, etc.).  When a package
has a ``source:`` resolver configured, that resolver creates the provider.
The ``hook-sdist`` and ``hook-prebuilt`` profiles delegate provider creation
to the package's required ``get_resolver_provider`` hook and validate that it
returns a :class:`~fromager.resolver.BaseProvider`.
The hook may ignore or replace the profile's index URL, but the profile's
value is stable across Fromager commands.
Otherwise, override plugins can replace the provider for a specific package
via the ``get_resolver_provider`` hook, after which the legacy resolver
settings are used.

Hook downloads accept explicit artifact kinds and adapt legacy paths using
profile-specific defaults. If no download hook exists, the profile selects the
standard sdist or wheel downloader and its destination directory. Hook errors
propagate with context instead of triggering a fallback. In-process callers
pass the downloaded path and kind to preparation: ``sdist`` and ``tarball``
are unpacked, while ``git_checkout`` uses the checkout directory. The checkout
uses the same double-nested work directory pattern as an unpacked archive;
the directory names can differ for normalized package names.
The default Git preparer rejects a checkout with local changes before applying
patches, project overrides, and Rust vendoring. Git status does not prove that the
checkout is the original clone or preserve it after preparation. Build metadata
is written after preparation but is not used to choose the preparation path.
With ``--no-cleanup``, downloading to an existing checkout fails and preserves
its files for inspection. Enable cleanup or use a new work directory to
download and prepare a fresh checkout. Git status cannot detect changes to
patch or settings files outside the checkout. If preparation left the checkout
clean, a manual second ``prepare-source`` call runs the preparation steps again.
The separate ``step prepare-source`` invocation accepts ``--source-kind`` and
``--source-path`` because it cannot retrieve the earlier Python download result.
``step download-source-archive --output-format json`` exposes that result's
actual path and kind without changing its default path-only output.
Without ``--source-kind``, it keeps the legacy archive behavior.
Configured prebuilt resolvers select the prebuilt bootstrap path. Fresh
external wheels use their ``download()`` contract and are staged in the
prebuilt wheel directory. For local mirror URLs, bootstrap, build, and
download-sequence reuse the exact file the mirror serves, so they do not
rerun the configured download hook or pick a different same-named copy.
Test-mode fallback downloads directly.
When a fresh configured wheel shares a filename with an older cached wheel,
the local mirror and later build replay use the fresh staged wheel.
Legacy build downloads still pass through the build wheel directory before
the mirror moves them to downloads.
See :ref:`download_source_hook` for the return contract and compatibility rules.

.. versionchanged:: 0.102.0
   Explicit ``DownloadKind.git_checkout`` results can be prepared without
   unpacking an archive. Configured source resolvers also select the sdist
   build method. Git checkout resolvers use PEP 517 by default; hook sdist
   resolvers require an explicit ``build_sdist: pep517`` or
   ``build_sdist: tarball``. PyPI sdist resolvers
   repack a tarball. Both configured strategies take precedence over an installed
   ``build_sdist`` override and log a warning when it is ignored. Legacy
   settings continue to use the override. Configured prebuilt profiles use
   their source provider after a local cache check, and local mirror URLs
   bypass configured download hooks during replay.

Version Filtering Window
-------------------------

Two age-based filters can narrow the set of acceptable versions:

.. code-block:: text

   ◄── too old ──┤  acceptable window  ├── too new ──►

                 │                      │
            max_age cutoff         cooldown cutoff
          (reject before this)   (reject after this)

- **Cooldown** rejects releases that are too new.  It ensures a
  minimum time has passed since publication, guarding against
  problematic releases.  Configurable per package; bypassed for
  exact version pins (``==``).

- **Max age** rejects releases that are too old.  Used primarily in
  ``multiple_versions`` mode to limit the range of versions built.

When both are active, only versions published within the window are
considered.  If all source candidates are filtered out, the behavior
depends on the mode: in single-version mode a warning is logged and all
candidates are kept; in ``multiple_versions`` mode only the newest
candidate is retained.  A source provider with no matching candidates
raises a resolution error; it is not replaced by a cache-server lookup.

Flat Resolution by Design
-------------------------

Fromager deliberately does **not** use resolvelib's transitive
dependency resolution.  Every provider's ``get_dependencies()`` method
returns an empty list.  This means resolution is a simple "find the
best matching version" operation, not a full constraint solver with
backtracking.

Transitive dependencies are handled by the bootstrap engine's own DFS
loop: after a package is built, its install dependencies are extracted
from the wheel metadata and pushed onto the work stack as new
``RESOLVE`` phase items.  This separation keeps the resolver stateless
and makes each resolution call independent and thread-safe.

Per-Package Configuration
-------------------------

Package settings files (YAML) can configure the resolver for each
package independently: resolver type (PyPI, GitHub tags, GitLab tags,
hook-based, or blocked), index URL, cooldown, tag pattern, and
override plugins.

See :doc:`package-settings` for how settings are loaded and merged.
