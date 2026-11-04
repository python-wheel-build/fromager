Multiple Version Bootstrap
==========================

.. versionadded:: 0.83.0

By default, fromager resolves each package to its single highest matching
version. The ``--multiple-versions`` flag changes this behavior so that
fromager resolves and builds **all versions** that match each requirement
specifier, rather than only the highest one.

This is different from ``--skip-constraints``, which lets you build a
specific set of conflicting pinned versions.  ``--multiple-versions``
discovers and builds every matching version automatically.  See
:doc:`multiple-versions` for the ``--skip-constraints`` option.

When to Use This
----------------

Use ``--multiple-versions`` when you need to:

- Populate a private package index with every available version of a package
- Build a broad wheel collection that serves consumers pinned to different
  versions
- Test that multiple versions of a package all build from source in your
  environment

.. note::

   The resulting wheel collection is **not** meant to be installed as a single
   coherent set. Each version is built independently.

How to Enable It
----------------

Pass ``--multiple-versions`` to either ``bootstrap`` or
``bootstrap-parallel``:

.. code-block:: bash

   # Serial bootstrap
   fromager bootstrap --multiple-versions 'requests>=2.28'

   # Parallel bootstrap
   fromager bootstrap-parallel --multiple-versions 'requests>=2.28'

This resolves every version of ``requests`` that satisfies ``>=2.28`` and
bootstraps each one.

You can also use a requirements file:

.. code-block:: bash

   fromager bootstrap --multiple-versions -r requirements.txt

How It Works
------------

1. **Resolution** --- For each requirement, fromager queries the package index
   and collects all versions matching the specifier. Without the flag, only the
   highest version is returned.

2. **Graph population** --- Every resolved version is added to the dependency
   graph. The highest version is processed first.

3. **Build** --- Each version is bootstrapped independently: its source is
   downloaded, its dependencies are resolved, and a wheel is built.

4. **Error handling** --- If a particular version fails to build, fromager logs
   a warning, removes that version from the dependency graph, and continues
   with the remaining versions. A summary of failed versions is printed at the
   end.

5. **Dependent pruning** --- When a *runtime* (install) dependency of a
   package fails to resolve or build, the dependent package has already been
   built: fromager must build a package before it can read the wheel metadata
   that declares its runtime dependencies. At the end of the bootstrap,
   fromager reconciles these failures and prunes each dependent whose
   requirement can no longer be satisfied: the package is removed from
   ``build-order.json`` and ``graph.json``, its built wheel and sdist are
   deleted, and it is recorded in ``partial-failures.json``. A dependent is
   only pruned when no remaining built version of the dependency satisfies
   its specifier *and requested extras* --- if another version of the
   dependency built successfully, or the requested extra's own dependencies
   are all present, the dependent is kept. Pruning cascades transitively to
   the dependent's own dependents. A dependency that is only required
   through an *extra* (``bar[feature] -> baz``) does not prune the shared
   package: the bare package stays available for its other consumers, and
   only the dependents that requested the extra are pruned. When wheel
   metadata cannot be read (``--sdist-only`` runs), a failure cannot be
   classified and the dependent is kept rather than pruned.

6. **Constraints disabled** --- ``constraints.txt`` generation is
   **automatically skipped** because a constraints file cannot represent
   multiple versions of the same package. You do not need to pass
   ``--skip-constraints`` separately.

Output Files
~~~~~~~~~~~~

When ``--multiple-versions`` is active:

.. versionchanged:: 0.95.0
   Failed versions are recorded in ``partial-failures.json``. The file is
   removed when a subsequent run has no reportable failures.

- ``build-order.json`` --- created normally, listing every version built
- ``graph.json`` --- created normally, containing all versions in the
  dependency graph
- ``partial-failures.json`` --- created when one or more versions fail. Each
  failure includes the package name, version, phase, exception type, and
  message. Packages pruned because a runtime dependency is unavailable are
  recorded here with the phase ``pruned due to unresolved runtime dependency``.
- ``constraints.txt`` --- **not generated**

The report contains a top-level ``failures`` list. For a resolved version,
``name`` includes the package version (for example, ``requests==2.28.0``),
and ``version`` contains the version separately. For an unresolved
requirement, ``version`` is ``null`` and ``name`` contains only the package
name.

.. code-block:: json

   {
     "failures": [
       {
         "name": "requests==2.28.0",
         "version": "2.28.0",
         "phase": "failed during build phase",
         "error_type": "CalledProcessError",
         "message": "build command failed"
       }
     ]
   }

Combining with Other Flags
--------------------------

``--test-mode``
  Supported with serial ``bootstrap`` only. Failures are collected and
  reported at the end rather than aborting early (same behavior as without
  ``--multiple-versions``). When combined with ``--multiple-versions``,
  failed versions are also included in ``partial-failures.json`` and test
  mode retains its non-zero exit code for recorded failures.

``--skip-constraints``
  Redundant when ``--multiple-versions`` is set. Fromager automatically
  disables constraint generation. Passing both flags explicitly is
  harmless --- no duplicate log messages are emitted.

``--max-release-age``
  Works together with ``--multiple-versions``. Only versions published
  within the specified number of days are considered.

``bootstrap-parallel``
  The flag is passed through to the serial bootstrap phase (sdist-only),
  then the parallel build phase builds the remaining wheels.
  ``--test-mode`` is not available in parallel builds.

Complete Example
----------------

Suppose you want to build every ``requests`` release from 2.28 onward.

**1. Create a requirements file**

.. code-block:: text

   requests>=2.28

**2. Run the bootstrap**

.. code-block:: bash

   fromager bootstrap --multiple-versions \
     --sdists-repo ./sdists-repo \
     --wheels-repo ./wheels-repo \
     --work-dir ./work-dir \
     -r requirements.txt

**3. Verify the built wheels**

.. code-block:: bash

   find wheels-repo/downloads/ -name "requests-*.whl" | sort
   # requests-2.28.0-py3-none-any.whl
   # requests-2.28.1-py3-none-any.whl
   # requests-2.28.2-py3-none-any.whl
   # ...

If any version failed to build, the log output will include lines like:

.. code-block:: text

   WARNING requests: 1 version(s) failed to bootstrap
   WARNING   - requests==2.28.0: BuildError: ...

See Also
--------

- :doc:`multiple-versions` --- building specific conflicting versions
  with ``--skip-constraints``
- :doc:`graph-commands/understanding-multiple-versions` --- analyzing
  multiple versions in dependency graphs
- :doc:`bootstrap-constraints` --- using constraints for reproducible builds
