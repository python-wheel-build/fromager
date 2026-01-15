Bootstrap vs Build
==================

Fromager has two distinct modes of operation: **bootstrap** and **build**.
Understanding the difference is key to using fromager effectively.

.. seealso::

   :doc:`/using` covers practical command usage and examples.

Quick Comparison
----------------

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Aspect
     - Bootstrap
     - Build
   * - **Scope**
     - Entire dependency tree
     - Single package
   * - **Purpose**
     - Discover and resolve all dependencies
     - Compile source into wheel
   * - **Recursion**
     - Yes (processes dependencies)
     - No (one package only)
   * - **Input**
     - Requirements file or package specs
     - Package name + version + source URL
   * - **Output**
     - Dependency graph, build order, all wheels
     - One wheel file

Bootstrap Mode
--------------

The ``bootstrap`` command recursively discovers and builds all dependencies:

.. code-block:: text

   fromager bootstrap numpy
     ├── Resolve version → numpy==1.26.0
     ├── Download source
     ├── Extract build dependencies from pyproject.toml
     ├── bootstrap(setuptools)  ← Process build dependencies first
     ├── Build wheel (with build deps available)
     ├── Extract install dependencies from wheel metadata
     └── bootstrap(cython)  ← Process each install dependency
           └── Resolve version → cython==3.0.0, then repeat...

**Key operations:**

1. Version resolution for all packages
2. Dependency graph construction
3. Build order determination
4. Wheel building (for each discovered package)

**When to use:** Initial discovery of what needs to be built, creating a complete
wheel collection from scratch.

Build Mode
----------

The ``build`` command compiles a single package without recursion:

.. code-block:: text

   fromager build numpy 1.26.0 https://pypi.org/simple/
     ├── Download sdist
     ├── Apply patches
     ├── Create build environment
     ├── Run pip wheel
     └── Output: numpy-1.26.0-cp311-linux_x86_64.whl

**Key operations:**

1. Source download and preparation
2. Build environment setup
3. Wheel compilation
4. No dependency discovery or recursion

**When to use:** Production builds where the build order is already known
(from a previous bootstrap), CI/CD pipelines, rebuilding individual packages.

Relationship
------------

While ``bootstrap`` and ``build`` share some common steps (downloading sources,
applying patches, running pip wheel), they are separate implementations optimized
for different use cases. Bootstrap maintains state across the entire dependency tree,
while build operates statelessly on a single package.

The ``build-sequence`` and ``build-parallel`` commands bridge these modes by reading
a ``build-order.json`` file (produced by bootstrap) and invoking the build logic
for each package in the specified order.

Typical Workflow
----------------

1. **Development:** Use ``bootstrap`` to discover all dependencies and create
   initial wheel collection

2. **Production:** Use ``build-sequence`` or ``build-parallel`` with the
   ``build-order.json`` from bootstrap to rebuild deterministically

3. **Fixes:** Use ``build`` to rebuild individual packages after applying patches
