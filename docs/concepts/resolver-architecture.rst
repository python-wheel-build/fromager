Resolver Architecture
=====================

Fromager finds package versions on a Python index, in Git tags, or
through a plugin, and turns the selected source into something it can
build.

.. seealso::

   :doc:`architecture-overview` maps the major subsystems.

   :doc:`bootstrapper-architecture` covers how resolution fits into the
   bootstrap pipeline.

From Requirement to Build
-------------------------

A **provider** finds versions. A **source resolver** selects the
provider, downloads the artifact, and selects the sdist build method.
Prebuilt profiles download a wheel and skip source preparation and
building.

For a source package, the work has four steps:

1. **Resolve:** a provider finds matching versions and their download URLs.
2. **Download:** the source resolver returns a ``DownloadedSource`` with
   a local path and an artifact kind.
3. **Prepare:** Fromager unpacks an archive or prepares a Git checkout,
   then applies patches and other source changes.
4. **Build:** Fromager creates an sdist with the selected build method,
   then builds the wheel.

Resolution Strategies
---------------------

During bootstrap, ``BootstrapRequirementResolver`` keeps a thread-safe
session cache of resolved requirement rules and discovered versions.
For each requirement rule, it tries in order:

1. the session cache, so repeated rules need no further lookup
2. the previous dependency graph, if one is available
3. the selected provider, which may query PyPI, GitHub, or GitLab

New results are merged into the session cache and filtered by the
current requirement.

Two cases need separate handling:

- **Direct-reference URL requirements**, including Git URLs, are rejected.
  Use a ``source:`` provider in package settings instead.
- **Prebuilt packages** may use the local wheel server before an
  external provider. For source builds the wheel cache is checked only
  after a version is selected; it never supplies fallback source
  versions.

Provider Hierarchy
------------------

Providers inherit from ``BaseProvider``, which implements resolvelib's
``ExtrasProvider`` interface. The bootstrap engine and CLI commands call
their common ``find_matches()`` method.

.. code-block:: text

   BaseProvider
   ├── PyPIProvider
   │   └── PyPICacheProvider
   ├── GenericProvider
   │   ├── GitHubTagProvider
   │   └── GitLabTagProvider
   └── VersionMapProvider

- ``PyPIProvider`` queries a Python package index such as PyPI or a
  mirror, filtering by platform, Python version, and yanked status.
- ``PyPICacheProvider`` queries Fromager's wheel server without a
  cooldown. It serves wheel-cache lookups, not source version resolution.
- ``GenericProvider`` pairs a version-source callback with a
  configurable matcher; it is the base of the tag providers.
- ``GitHubTagProvider`` and ``GitLabTagProvider`` query repository tags
  and parse versions from tag names. GitLab also reports timestamps for
  age filtering.
- ``VersionMapProvider`` uses an existing version-to-URL mapping, such
  as results from an earlier resolution or a URL template.

Selecting a Provider
--------------------

.. versionchanged:: 0.103.0
   Packages can select a source resolver through ``source:`` settings,
   which replaces the legacy resolver settings for those packages.

A package's YAML settings select the provider and its parameters, such
as the index URL or tag pattern. With ``source:`` configured, the source
resolver creates the provider and owns the index URL; caller-supplied
index URLs are ignored. Without ``source:``, Fromager uses the legacy
resolver settings and the package's ``get_resolver_provider`` override
when present.

Hook Profiles
~~~~~~~~~~~~~

The ``hook-sdist`` and ``hook-prebuilt`` profiles connect ``source:``
settings to existing plugins. A package must provide at least one of
``get_resolver_provider`` or ``download_source``.

- **With a resolver hook:** the hook creates the provider and must
  return a :class:`~fromager.resolver.BaseProvider`. It receives
  ``index_url`` as ``sdist_server_url`` and may ignore or replace it.
- **Without a resolver hook:** Fromager finds versions on ``index_url``.
  ``hook-sdist`` considers sdists and wheels for any platform;
  ``hook-prebuilt`` considers wheels for the current platform. The
  download hook retrieves the artifact.

``hook-sdist`` defaults to PyPI; ``hook-prebuilt`` requires an explicit
index URL. The profile passes the same configured URL to the hook across
Fromager commands.

Update Reports
~~~~~~~~~~~~~~

``find-updates`` also uses the configured source resolver, including its
distribution types and index URL. Packages without ``source:`` retain
the legacy provider hook, distribution options, and index overrides.
Update reports ignore global and per-package cooldowns so recent
releases remain visible.

Downloading and Preparing Sources
---------------------------------

Passing Resolution Results to Downloads
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A configured resolver's ``download()`` receives only the version and the
download URL of the selected candidate. These values are saved in
``graph.json`` and ``build-order.json`` so a later command can download
the same source. The URL must contain everything the download needs,
including the Git ref:

.. code-block:: text

   git+https://host.example/repo.git@refs/tags/v1.0

.. versionchanged:: 0.103.0
   ``download()`` takes ``version`` and ``download_url`` instead of a
   ``Candidate``.

Artifact Kinds
~~~~~~~~~~~~~~

``DownloadedSource`` tells preparation how to handle the local path:

- ``sdist`` and ``tarball``: unpack the archive.
- ``git_checkout``: prepare the existing checkout in place.
- ``prebuilt_wheel``: use the wheel without source preparation.

Hook downloads can return an explicit kind or a legacy ``Path``, treated
as an sdist for ``hook-sdist`` and a wheel for ``hook-prebuilt``.
Without a download hook, the profile uses the standard sdist or wheel
downloader. Hook errors stop the operation with context; they do not
trigger a fallback.

See :ref:`download_source_hook` for the return contract and validation
rules.

Git Checkouts: Reuse and Preparation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Built-in archive resolvers cache downloaded files. Git resolvers keep
their checkouts in the work directory, under canonical package names:

.. code-block:: text

   work-dir/test-pkg-1.0/test-pkg-1.0/

At download time, an existing checkout is reused when it is a clean
clone of the same repository at the same commit, with submodules at
their recorded commits. A later build in the same work directory then
runs without contacting the Git host. The check is local only, so a tag
moved on the remote is not detected.

A checkout that cannot be reused is removed and cloned again. With
``--no-cleanup``, the download fails instead and keeps the files for
inspection.

At preparation time, the default Git preparer rejects local changes
before applying patches, project overrides, and Rust vendoring. A clean
Git status does not prove the checkout's origin, protect it from later
changes, or detect changed patch and settings files outside the
checkout. Build metadata is written after preparation and does not
select the preparation path. If preparation leaves the checkout clean,
a manual second ``prepare-source`` call runs preparation again.

Running Download and Preparation Separately
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Separate CLI invocations cannot share the Python ``DownloadedSource``
result. These options pass its information between steps:

- ``step download-source-archive --output-format json`` prints the path
  and kind; the default output is the path alone.
- ``step prepare-source --source-kind`` selects the artifact kind.
  Without it, providers with one supported source kind use that kind.
  Legacy settings and providers with multiple kinds default to ``sdist``;
  prebuilt wheels are excluded from inference.
- ``step prepare-source --source-path`` selects the downloaded path.
  Git checkouts must still use the standard double-nested work directory.

Building the Sdist
------------------

.. versionchanged:: 0.103.0
   Git checkouts can be prepared directly. Configured source resolvers
   also select the sdist build method.

For source builds, ``source.build_sdist`` selects the build method:

- ``pep517`` calls the package's build backend. Git checkout resolvers
  default to it.
- ``tarball`` repacks the prepared source without VCS metadata such as
  ``.git``. PyPI sdist resolvers default to it.
- ``hook`` calls the package's custom ``build_sdist`` hook. It can generate
  files or choose which directory to pack. A missing hook is an error.

``hook-sdist`` requires an explicit build method. Other profiles that build
from source can also select ``hook``. The ``pep517`` and ``tarball`` methods
skip installed build hooks with a warning. Without ``source:``, Fromager
uses the hook when present, or the default otherwise.

Hooks that delegate to ``default_build_sdist()`` inherit its default VCS
exclusion for configured source profiles. An explicit ``exclude_vcs`` value
overrides this policy. Hooks that create archives directly choose their contents.

See :ref:`build_sdist_hook` for the arguments, archive rules, and an example.

Replaying a Build Order
-----------------------

.. versionchanged:: 0.103.0
   Sequence commands check recorded providers before replaying a build
   order.

``build-sequence`` and ``download-sequence`` validate every entry's
recorded ``source_provider`` against current settings before starting
any builds or downloads, including prebuilt entries whose URLs will be
skipped. A missing or different provider is an error. The comparison
uses provider names only, so replay should use the same package
settings. Older build orders without ``source_provider`` still work
with legacy settings; regenerate them before using a configured source.

``download-sequence`` calls the configured resolver's normal
``download()`` for source entries and skips source downloads for entries
recorded as runtime prebuilt fallbacks, even if source settings are
configured. Legacy packages retain their ``source_url_type`` selection
behavior. The two recorded fields have different purposes:

- ``source_provider`` identifies the effective configured provider.
- ``source_url_type`` is a legacy classification, not the downloaded
  artifact kind.

Prebuilt Wheel Downloads
------------------------

Configured prebuilt profiles skip source builds. Fresh external wheels
use the resolver's ``download()`` and are staged in the prebuilt wheel
directory. Test-mode fallback downloads directly.

For local mirror URLs, bootstrap, build, and download-sequence reuse the
exact file served by the mirror: they do not rerun a configured download
hook or select a different copy with the same filename. When a fresh
configured wheel replaces an older cached wheel with the same filename,
the mirror and later replay use the fresh staged wheel.

Legacy build downloads pass through the build wheel directory before the
mirror moves them to downloads.

Version Filtering Window
------------------------

Two age filters can narrow the set of matching versions:

.. code-block:: text

   ◄── too old ──┤  acceptable window  ├── too new ──►

                 │                      │
            max_age cutoff         cooldown cutoff
          (reject before this)   (reject after this)

- **Cooldown** rejects releases that are too new. It sets a minimum time
  since publication and can be configured per package. Exact top-level
  version pins (``==``) bypass it; pinned dependencies still use cooldown.
- **Max age** rejects releases that are too old. Used primarily in
  ``multiple_versions`` mode to limit the range of versions built.

Providers apply cooldown before the max-age filter. If cooldown removes
every matching candidate, resolution fails; the max-age fallback does not
bypass cooldown.

If the max-age filter excludes every remaining source candidate:

- In single-version mode, Fromager logs a warning and keeps all matching
  candidates for version selection.
- In ``multiple_versions`` mode, it keeps only the newest matching
  candidate.

If the source provider has no matching candidates at all, resolution
fails; Fromager does not look for fallback source versions on the wheel
cache server.

Flat Resolution by Design
-------------------------

Each resolver call selects matching versions for one requirement.
Every provider's ``get_dependencies()`` returns an empty list, so
resolvelib does not solve transitive dependencies or backtrack across
them.

Transitive dependencies are handled by the bootstrap engine's own DFS
loop: after a package is built, its install dependencies are extracted
from the wheel metadata and pushed onto the work stack as new ``RESOLVE``
phase items. Providers handle version lookup; the bootstrap engine
handles graph traversal.

Per-Package Configuration
-------------------------

Package settings files (YAML) configure the resolver for each package
independently: resolver type (PyPI, GitHub tags, GitLab tags, hook-based,
or blocked), index URL, cooldown, tag pattern, and override plugins.

See :doc:`package-settings` for how settings are loaded and merged.
