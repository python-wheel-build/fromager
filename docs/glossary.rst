Glossary
========

This glossary defines key terms used throughout Fromager's documentation and codebase.

.. glossary::
   :sorted:

   ABI
      Application Binary Interface. Defines binary compatibility between compiled
      code. Relevant when building platform-specific :term:`wheels <wheel>` that
      must match the target Python interpreter's ABI.

   bootstrap
      The process of recursively discovering and building all dependencies for a
      set of top-level requirements. Bootstrap resolves versions, downloads sources,
      builds wheels, and extracts installation dependencies—repeating for each
      discovered dependency until the entire dependency tree is processed. The output
      includes a :term:`dependency graph`, :term:`build order`, and all built
      :term:`wheels <wheel>`. See :doc:`/concepts/bootstrap-vs-build` for details.

   build
      The process of compiling a single package from source into a :term:`wheel`,
      without recursion. Unlike :term:`bootstrap`, the build command operates on
      one package at a time with a known version and source URL. See
      :doc:`/concepts/bootstrap-vs-build` for a comparison.

   build environment
      An isolated Python virtual environment created for building a specific package.
      It contains only the :term:`build dependencies <build-system dependency>` required
      to compile that package, ensuring reproducible builds. See also
      :term:`build isolation`.

   build isolation
      The practice of running each package build in its own isolated virtual
      environment to prevent interference between builds. Distinct from
      :term:`network isolation`, which restricts network access.

   build order
      The sequence in which packages must be built, determined by analyzing the
      :term:`dependency graph`. Packages are ordered bottom-up (topological sort)
      so that each package's dependencies are built before the package itself.
      Stored in ``build-order.json``. See :doc:`/files` for the file format.

   build sequence
      A command (``build-sequence``) that processes a pre-determined :term:`build order`
      file to build wheels in dependency order. Unlike :term:`bootstrap`, it does not
      perform dependency discovery—it simply builds each package in the specified order.
      See :doc:`/using` for usage details.

   build tag
      A numeric prefix added to :term:`wheel` filenames (e.g., ``-0-`` in
      ``package-1.0.0-0-py3-none-any.whl``) to differentiate wheels built by fromager
      from upstream wheels. This follows the wheel filename convention from
      :pep:`427`.

   build-backend dependency
      A dependency returned by :pep:`517` build backend hooks like
      ``get_requires_for_build_wheel()``. These are additional tools needed beyond
      the :term:`build-system dependencies <build-system dependency>` to build a wheel.
      Examples include ``cython`` for Cython extensions or ``numpy`` for packages
      compiling against NumPy headers. See :doc:`/concepts/dependencies`.

   build-sdist dependency
      A dependency needed specifically for building a :term:`source distribution`.
      Returned by the :pep:`517` ``get_requires_for_build_sdist()`` hook.
      See :doc:`/concepts/dependencies`.

   build-system dependency
      A dependency listed in ``pyproject.toml`` under ``[build-system].requires``,
      as defined by :pep:`518`. These are the foundational build tools (like
      ``setuptools``, ``flit-core``, or ``maturin``) installed before any build
      backend hooks are called. See :doc:`/concepts/dependencies`.

   built distribution
      A package format ready for installation without requiring a build step.
      :term:`Wheels <wheel>` are the standard built distribution format in Python.
      Contrast with :term:`source distribution`.

   candidate
      A potential version of a package discovered during :term:`resolution`. Candidates
      are evaluated against :term:`version specifiers <specifier>` and
      :term:`constraints` to select the best matching version.

   canonical name
      The normalized form of a Python package name, computed using
      ``packaging.utils.canonicalize_name()``. All letters are lowercase and runs of
      hyphens, underscores, and periods are replaced with a single hyphen (e.g.,
      ``My_Package`` becomes ``my-package``). See also :term:`override name` for the
      variant used in file paths. The :ref:`fromager-canonicalize` command converts
      names to canonical form.

   constraints
      Version specifications that control package :term:`resolution`. Provided via a
      ``constraints.txt`` file, they ensure specific versions are used or avoided
      during builds. Unlike :term:`requirements <requirement>`, constraints only
      apply when a package is already needed. See :doc:`/files` for format details.

   cyclic dependency
      A circular dependency where packages depend on each other, forming a loop
      (e.g., A depends on B, B depends on C, C depends on A). Cyclic dependencies
      can occur in two contexts:

      - **Build-time cycles** are problematic—packages require each other during
        the build process. These must be resolved (often by marking one package
        as :term:`pre-built <pre-built wheel>`) for the build to succeed.
      - **Install-time cycles** are acceptable—packages depend on each other only
        at runtime. These don't affect the build process since install dependencies
        are processed after the parent package is built.

   dependency graph
      A directed graph representing all packages and their relationships discovered
      during :term:`bootstrap`. Nodes represent resolved package versions, and edges
      capture the :term:`requirement` specifications and dependency types (toplevel,
      install, build-system, etc.). Stored in ``graph.json``. See :doc:`/files` and
      :doc:`/how-tos/graph-commands/index`.

   distribution name
      The actual package name as it appears in package files and indexes, which
      may have different casing than the :term:`canonical name`. For example,
      ``PyYAML`` is the distribution name while ``pyyaml`` is the canonical name.

   hook
      An extension point in fromager that allows customization of specific
      operations. Hooks include ``post_build``, ``prebuilt_wheel``, and
      ``post_bootstrap``. Multiple plugins can register for the same hook.
      See :doc:`/hooks` and :doc:`/customization`.

   install dependency
      A runtime dependency of a package, extracted from the built :term:`wheel`'s
      ``Requires-Dist`` metadata. These are processed after the parent package is
      built. See :doc:`/concepts/dependencies`.

   local cache
      Built :term:`wheels <wheel>` stored locally in ``wheels-repo/`` for reuse
      within a :term:`bootstrap` run. Fromager checks this cache before building
      to avoid redundant compilation.

   network isolation
      A build mode where :term:`source distribution` and :term:`wheel` building
      occurs without network access (using ``unshare -cn`` on Linux). This ensures
      builds only use locally available dependencies and cannot download arbitrary
      code. Distinct from :term:`build isolation`.

   override name
      A variant of :term:`canonical name` where hyphens are replaced with underscores
      (e.g., ``my-package`` becomes ``my_package``). Used for settings files, patch
      directories, and :term:`override plugins <override plugin>` because Python
      module names cannot contain hyphens. The :ref:`fromager-canonicalize` command
      can convert names to this format.

   override plugin
      A Python module registered as an entry point that provides custom implementations
      of fromager operations for specific packages. Unlike :term:`hooks <hook>`, overrides
      replace the default behavior entirely. Plugins can customize source acquisition,
      dependency resolution, building, and more. See :doc:`/hooks`.

   package index
      A server providing package metadata and downloads, following the
      :term:`Simple API` specification. :term:`PyPI` is the default public index.
      Also called a package repository.

   package repository
      A directory structure or server serving packages following the :pep:`503`
      :term:`Simple API`. Fromager creates a local package repository in
      ``wheels-repo/simple/`` during builds.

   patch
      A file (with ``.patch`` extension) that modifies source code before building.
      Patches are stored in the patches directory (default: ``overrides/patches/``)
      organized by package name and optionally version and :term:`variant`. Applied
      using ``patch -p1``. See :doc:`/customization`.

   PEP 503
      Python Enhancement Proposal defining the Simple Repository API—the directory
      structure for :term:`package indexes <package index>`. Fromager creates a
      PEP 503-compliant local repository for built wheels. See :pep:`503`.

   PEP 517
      Python Enhancement Proposal defining the interface between build frontends
      (like pip) and build backends (like setuptools). Specifies hooks like
      ``get_requires_for_build_wheel()`` that fromager uses to discover
      :term:`build-backend dependencies <build-backend dependency>`. See :pep:`517`.

   PEP 518
      Python Enhancement Proposal specifying the ``pyproject.toml`` file format
      for declaring :term:`build-system dependencies <build-system dependency>`.
      See :pep:`518`.

   pre-built wheel
      A :term:`wheel` that is used directly without building from source. Configured
      via the ``pre_built`` setting for a :term:`variant`. Useful for packages that
      cannot be built from source or when using vendor-provided binaries.

   pre-release version
      A package version containing alpha (``a``), beta (``b``), or release candidate
      (``rc``) components. By default, fromager ignores pre-release versions unless
      explicitly requested via requirements or :term:`constraints`.
      See :doc:`/how-tos/pre-release-versions`.

   PyPI
      The Python Package Index (https://pypi.org), the default public
      :term:`package index` for Python packages. Fromager downloads
      :term:`source distributions <source distribution>` from PyPI by default.

   remote cache
      A :term:`package index` with previously built packages, used for distributed
      builds. Configured via ``--cache-wheel-server-url`` to avoid rebuilding
      packages that already exist remotely.

   repeatable builds
      A feature that uses the :term:`dependency graph` from a previous
      :term:`bootstrap` to ensure consistent package versions across builds. Enabled
      via the ``--previous-bootstrap-file`` option. See :doc:`/how-tos/repeatable-builds`.

   requirement
      A package dependency specification that may include version constraints,
      extras, and environment markers. For example, ``requests>=2.28.0`` or
      ``numpy[dev]>=1.20; python_version>="3.9"``. See also :term:`specifier`.

   resolution
      The process of determining specific package versions from :term:`requirement`
      specifications. The :term:`resolver` evaluates available :term:`candidates <candidate>`
      against :term:`constraints`, markers, and other factors to select the best
      matching version.

   resolver
      The component that performs :term:`resolution`, selecting specific package
      versions that satisfy all :term:`requirements <requirement>` and
      :term:`constraints`. Uses :term:`resolver providers <resolver provider>` to
      discover available versions.

   resolver provider
      A strategy class that supplies version :term:`candidates <candidate>` during
      :term:`resolution`. The default provider queries :term:`PyPI`, but custom
      providers can resolve versions from GitHub tags, GitLab tags, or other sources.
      See :doc:`/hooks`.

   sdist-only mode
      A :term:`bootstrap` mode (``--sdist-only``) that builds :term:`source
      distributions <source distribution>` but skips :term:`wheel` building for
      install dependencies. Useful for quickly generating :term:`build order` files
      when wheel compilation is time-consuming.

   settings
      Configuration options that customize package building. Can be global (in
      ``overrides/settings.yaml``) or per-package (in ``overrides/settings/<name>.yaml``).
      Settings control environment variables, source URLs, :term:`variants <variant>`,
      and more. See :doc:`/customization` and :doc:`/config-reference`.

   Simple API
      The :pep:`503` specification for :term:`package index` directory layout.
      Uses a ``/simple/<package>/`` URL structure with HTML pages listing available
      package files. Fromager serves built wheels via a local Simple API server.

   source distribution
      A package archive containing source code, typically a ``.tar.gz`` file. Also
      called "sdist". Fromager downloads sdists, applies :term:`patches <patch>`,
      and builds :term:`wheels <wheel>` from them. Defined by Python packaging
      standards. See the `PyPA glossary <https://packaging.python.org/en/latest/glossary/#term-Source-Distribution-or-sdist>`__.

   source type
      The origin of a package's source code. Values include:

      - ``sdist``: Downloaded from a :term:`package index` (default)
      - ``prebuilt``: Using a :term:`pre-built wheel`
      - ``git``: Cloned from a git repository URL
      - ``override``: Custom source via :term:`override plugin`

   specifier
      The version constraint portion of a :term:`requirement`, such as ``>=1.0,<2.0``
      in ``package>=1.0,<2.0``. Specifiers define which versions satisfy a requirement.

   toplevel dependency
      A package specified directly via CLI arguments or a requirements file, as
      opposed to dependencies discovered transitively. These are the starting points
      for :term:`bootstrap`. See :doc:`/concepts/dependencies`.

   variant
      A named build configuration for producing different versions of packages.
      Commonly used for hardware-specific builds (e.g., ``cpu``, ``cuda``, ``rocm``).
      Each variant can have its own environment variables, patches, and settings.
      The default variant is ``cpu``. See :doc:`/customization`.

   VCS
      Version Control System, such as git or mercurial. Fromager supports building
      from VCS URLs (e.g., ``git+https://github.com/...``) specified in requirements.

   vendoring
      The practice of including dependencies within a package's source code for
      offline or isolated builds. Some packages vendor their dependencies to avoid
      network access during builds.

   wheel
      A :term:`built distribution` format (:pep:`427`) containing compiled code
      ready for installation. Wheel files have the ``.whl`` extension and include
      platform and Python version compatibility tags in their filename.

   work directory
      The directory (default: ``work-dir/``) where fromager stores working files
      during builds. Contains :term:`build order`, :term:`dependency graph`,
      constraints, logs, and per-package build artifacts. See :doc:`/files`.
