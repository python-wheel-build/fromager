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
   │          │ age filter empties result                  │
   │          ▼                                            │
   │  4. Cache server fallback                             │
   │     (multiple_versions mode only)                     │
   └───────────────────────────────────────────────────────┘

   Git URL requirements (top-level only) bypass this
   chain entirely: the repo is cloned and the version
   is extracted from package metadata.

Versions discovered from any source are merged into the session cache.
Subsequent requests for the same package skip the network entirely if
the cache already contains a matching version.

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
       server.  No cooldown applied.  Used as a fallback when age
       filtering eliminates all candidates.
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

Per-package settings in YAML can select which provider to use and
configure its parameters (index URL, tag pattern, etc.).  Override
plugins can replace the provider entirely for a specific package via
the ``get_resolver_provider`` hook.

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
considered.  If all candidates are filtered out, the behavior depends
on the mode: in single-version mode a warning is logged and all
candidates are kept; in ``multiple_versions`` mode the cache server
fallback is tried instead.

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
