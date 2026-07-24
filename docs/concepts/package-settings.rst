Package Settings
================

Fromager uses a layered settings system to configure how each package
is resolved, downloaded, patched, and built.  Settings flow from YAML
files on disk through a merge pipeline into a single facade object
used by the build pipeline.

.. seealso::

   :doc:`/reference/config-reference` documents every configuration
   field.  :doc:`architecture-overview` maps the major subsystems.

Settings Loading Flow
---------------------

.. code-block:: text

   CLI flags
   (--settings-file, --settings-dir, --patches-dir)
         │
         ▼
   Settings.from_files()
   ├── Load settings.yaml ──► SettingsFile (global config)
   └── Glob settings/*.yaml ──► PackageSettings (one per package)
         │
         ▼
   Settings object (held by WorkContext)
         │
         │  package_build_info("torch")  (on demand, cached)
         ▼
   PackageBuildInfo
   (single facade used by the build pipeline)

``PackageBuildInfo`` objects are created lazily the first time a
package is queried and cached for the rest of the run.

Directory Structure
-------------------

.. code-block:: text

   overrides/
   ├── settings.yaml              # Global settings
   ├── settings/                  # Per-package settings
   │   ├── torch.yaml
   │   ├── flash-attn.yaml
   │   └── ...
   └── patches/                   # Patches
       ├── torch/                 # Unversioned (all versions)
       │   ├── 001-fix.patch
       │   └── cpu/               # Variant-specific
       │       └── 002-cpu.patch
       └── torch-2.4.0/           # Version-specific
           └── 001-ver.patch

Package YAML filenames use the canonicalized package name (lowercase,
hyphens).  All three directories are configurable via CLI flags.

Merge Order
-----------

Settings are merged from least-specific to most-specific.  Later
layers override earlier ones:

.. code-block:: text

   ┌──────────────────────────────────────────────────┐
   │  1. Pydantic field defaults                      │
   │     (empty env, default build options, etc.)     │
   │                                                  │
   │  2. Global settings.yaml                         │
   │     (SBOM config, global changelog)              │
   │                                                  │
   │  3. Per-package YAML file                        │
   │     (env, resolver, build options, patches, ...) │
   │                                                  │
   │  4. Variant overrides (within package YAML)      │
   │     (env vars, pre_built, wheel_server_url)      │
   │                                                  │
   │  5. Version-specific patches and changelog       │
   │     (patches/<pkg>-<version>/, changelog entries)│
   │                                                  │
   │  6. Override plugin hooks (runtime)              │
   │     (update_extra_environ can mutate env vars)   │
   └──────────────────────────────────────────────────┘

For environment variables specifically, the merge order within a
single ``get_extra_environ()`` call is: parallel-jobs settings, build
environment paths, package-level ``env``, then variant-level ``env``.
Entries can reference earlier values using ``$VAR`` template syntax.

PackageBuildInfo Facade
-----------------------

``PackageBuildInfo`` is the single interface the build pipeline uses to
query all package configuration.  It wraps a ``PackageSettings`` and
adds variant awareness, patch discovery, and template resolution.

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Category
     - What it provides
   * - **Identity**
     - Package name, variant, whether a config file exists, override
       plugin module
   * - **Resolution**
     - Sdist server URL, include wheels/sdists flags, platform
       filtering, per-package cooldown override
   * - **Build config**
     - Environment variables, parallel jobs, exclusive build flag,
       PEP 517 config settings, build directory
   * - **Source**
     - Download URL and filename templates with ``${version}``
       substitution, git submodule options
   * - **Patches**
     - Merged list of unversioned + version-specific + variant-specific
       patch files, sorted by filename
   * - **Metadata**
     - Build tag (from changelog length), annotations, PURL config,
       pyproject.toml overrides

See :doc:`/reference/config-reference` for the full field reference.
