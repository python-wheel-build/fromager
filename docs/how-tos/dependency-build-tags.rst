Dependency-Chained Build Tags
==============================

When building packages that depend on system libraries or other packages, you may
want the build tag to automatically increment when any dependency's build
configuration changes. This ensures downstream packages are rebuilt when their
dependencies are updated, even if the downstream package itself hasn't changed.

Use Cases
---------

Dependency-chained build tags are particularly useful for:

* **Platform Dependencies**: Packages that depend on CUDA, ROCm, or other
  accelerator stacks where the platform version changes independently of your
  package code.

* **Midstream Builds**: When you maintain patches or configuration for upstream
  packages and need downstream dependents to rebuild when you change those
  patches.

* **Transitive Rebuilds**: Ensuring an entire dependency chain rebuilds when a
  base library changes (e.g., when updating OpenSSL, all packages that depend
  on it should get new build tags).

How It Works
------------

Build tags are calculated as:

.. code-block:: text

   build_tag = own_changelog_count + sum(dependency_build_tags)

Dependencies are resolved **recursively** and **transitively**. If package A
depends on B, and B depends on C, then A's build tag includes changes from both
B and C.

Basic Example
-------------

Consider a simple dependency chain where ``torch`` depends on ``cuda-toolkit``:

**overrides/settings/cuda-toolkit.yaml**:

.. code-block:: yaml

   changelog:
     "12.8":
       - "Initial CUDA 12.8 support"
     "12.9":
       - "Updated to CUDA 12.9"

**overrides/settings/torch.yaml**:

.. code-block:: yaml

   dependencies:
     - cuda-toolkit
   changelog:
     "2.0.0":
       - "Initial build"

When you build ``torch==2.0.0`` with CUDA 12.9:

* ``cuda-toolkit`` has 1 changelog entry for version 12.9 → build tag = ``1``
* ``torch`` has 1 own changelog entry + 1 from cuda-toolkit → build tag = ``2``

If you later add another CUDA changelog entry:

.. code-block:: yaml

   changelog:
     "12.9":
       - "Updated to CUDA 12.9"
       - "Fixed memory issue"  # New entry

Now:

* ``cuda-toolkit`` version 12.9 → build tag = ``2``
* ``torch`` version 2.0.0 → build tag = ``3`` (automatically incremented!)

The wheel filename becomes: ``torch-2.0.0-3-cp311-cp311-linux_x86_64.whl``

Transitive Dependencies
-----------------------

Dependencies are resolved transitively through the entire chain.

**overrides/settings/triton.yaml**:

.. code-block:: yaml

   dependencies:
     - cuda-toolkit
   changelog:
     "2.3.0":
       - "Triton for CUDA 12.x"

**overrides/settings/torch.yaml**:

.. code-block:: yaml

   dependencies:
     - triton
   changelog:
     "2.0.0":
       - "Initial build"

Build tags for ``torch==2.0.0``:

* ``cuda-toolkit`` (version 12.9): 2 changelog entries → build tag = ``2``
* ``triton`` (version 2.3.0): 1 own + 2 from cuda-toolkit → build tag = ``3``
* ``torch`` (version 2.0.0): 1 own + 3 from triton → build tag = ``4``

Notice that ``torch`` **automatically includes** ``cuda-toolkit``'s changes even
though it only directly lists ``triton`` as a dependency.

Multiple Dependencies
---------------------

A package can depend on multiple packages. All dependency build tags are summed.

**overrides/settings/vllm.yaml**:

.. code-block:: yaml

   dependencies:
     - torch
     - triton
     - cuda-toolkit
   changelog:
     "0.3.0":
       - "Initial vLLM build"

If each dependency has a build tag of 2, then:

.. code-block:: text

   vllm build_tag = 1 (own) + 2 (torch) + 2 (triton) + 2 (cuda-toolkit) = 7

"Fake Packages" for Platform Dependencies
------------------------------------------

You can create settings files for platform dependencies (like CUDA, ROCm) that
don't actually exist as Python packages. These act as markers to track platform
version changes.

**overrides/settings/cuda-toolkit.yaml**:

.. code-block:: yaml

   # No source code - just a version marker
   changelog:
     "12.8":
       - "CUDA 12.8.0 release"
     "12.9":
       - "CUDA 12.9.0 release"

**overrides/settings/rocm-runtime.yaml**:

.. code-block:: yaml

   changelog:
     "6.0":
       - "ROCm 6.0 release"
     "6.1":
       - "ROCm 6.1 release"

Now packages can depend on these platform markers:

.. code-block:: yaml

   dependencies:
     - cuda-toolkit  # or rocm-runtime for ROCm builds

Circular Dependency Detection
------------------------------

Fromager automatically detects and prevents circular dependencies:

**overrides/settings/package-a.yaml**:

.. code-block:: yaml

   dependencies:
     - package-b

**overrides/settings/package-b.yaml**:

.. code-block:: yaml

   dependencies:
     - package-a

This will raise an error:

.. code-block:: text

   ValueError: Circular dependency detected: package-a appears in
   dependency chain: package-a -> package-b -> package-a

Scope and Limitations
----------------------

**Version-Independent**

Dependencies apply to **all versions** of a package. You cannot specify
different dependencies for different versions, or use version constraints:

.. code-block:: yaml

   dependencies:
     - torch          # ✓ Correct
     - torch>=2.0     # ✗ Not supported
     - torch; sys_platform=='linux'  # ✗ Not supported

**Per-Package, Not Per-Variant**

Dependencies are package-level, not variant-level. If you need different
dependencies for CUDA vs ROCm variants, use separate packages or platform markers.

**Build Tags Only**

The ``dependencies`` field only affects build tag calculation. It does **not**:

* Add runtime dependencies to wheel metadata
* Affect dependency resolution during bootstrap
* Change the build environment or compilation flags

Best Practices
--------------

1. **Use Semantic Changelog Entries**: Write clear changelog entries that
   explain what changed and why a rebuild is needed.

2. **Minimize Dependencies**: Only list direct dependencies that actually affect
   the build. Transitive dependencies are included automatically.

3. **Platform Markers**: Use fake packages for system dependencies (CUDA, ROCm,
   OpenSSL) to track platform version changes separately from Python packages.

4. **Testing**: When adding a dependency, verify the build tag increments as
   expected by checking the wheel filename.

See Also
--------

* :doc:`/reference/config-reference` - Full configuration reference
* :doc:`/customization` - Comprehensive customization guide
