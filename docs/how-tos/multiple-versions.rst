Build Collections with Multiple Versions of the Same Package
============================================================

In some cases, you may want to build collections of wheels that contain
conflicting versions of the same package. This is useful for scenarios such as:

- Building large collections for broader package indexes
- Testing jobs that need to build multiple conflicting versions
- Creating wheel collections that don't need to resolve to a single installable set of packages

By default, fromager generates a `constraints.txt` file during the bootstrap
process to ensure that all packages resolve to a compatible set of versions that
can be installed together. However, this validation step can be bypassed using
the `--skip-constraints` option.

Using --skip-constraints
------------------------

The `--skip-constraints` option allows you to skip the generation of the
`constraints.txt` file, enabling the building of packages with conflicting
version requirements:

.. code-block:: bash

   fromager bootstrap --skip-constraints package1==1.0.0 package2==2.0.0

When this option is used:

- The `constraints.txt` file will **not** be generated in the work directory
- The `build-order.json` and `graph.json` files are still created normally
- All packages specified will be built, even if they have conflicting dependencies
- A log message "skipping constraints.txt generation as requested" will be recorded

Example Use Case
----------------

Consider building both `django==3.2.0` and `django==4.0.0` in the same
collection:

.. code-block:: bash

   fromager bootstrap --skip-constraints django==3.2.0 django==4.0.0

Without `--skip-constraints`, this would fail because the two versions conflict.
With the flag, both versions will be built and stored in the wheels repository.

Important Considerations
------------------------

- **No installation validation**: The resulting wheel collection may not be
  installable as a single coherent set
- **Build sequence preservation**: The dependency resolution and build order
  logic still applies to each package individually
- **Intended for advanced use cases**: This option is primarily intended for
  specialized scenarios where version conflicts are acceptable or desired

The graph and build-sequence files can already handle multiple conflicting
versions, so this change simply allows bypassing the final constraints
validation step that ensures pip-compatibility.

Complete Example
----------------

This example demonstrates a complete walkthrough of using the ``--skip-constraints``
option to build wheel collections containing conflicting package versions.

Use Case
~~~~~~~~

Suppose you need to build a package index that contains multiple versions of the
same package for different downstream consumers. For example, you might want to
include both Django 3.2 and Django 4.0 in your collection.

Requirements Files
~~~~~~~~~~~~~~~~~~

Create a requirements file with conflicting versions:

**requirements-conflicting.txt**

.. code-block:: text

   django==3.2.0
   django==4.0.0
   requests==2.28.0

Normally, this would fail with a conflict error because both Django versions
cannot be installed together.

Running with --skip-constraints
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   fromager bootstrap --skip-constraints \
     --sdists-repo ./sdists-repo \
     --wheels-repo ./wheels-repo \
     --work-dir ./work-dir \
     -r requirements-conflicting.txt

Expected Behavior
~~~~~~~~~~~~~~~~~

1. **Success**: Both Django versions will be built successfully
2. **Output Files**:

   - ``build-order.json`` - Contains build order for all packages
   - ``graph.json`` - Contains dependency resolution graph
   - No ``constraints.txt`` file is generated

3. **Wheel Repository**: Contains wheels for both Django versions and their respective dependencies

Verification
~~~~~~~~~~~~

Check that both versions were built:

.. code-block:: bash

   find wheels-repo/downloads/ -name "Django-*.whl"
   # Expected output:
   # wheels-repo/downloads/Django-3.2.0-py3-none-any.whl
   # wheels-repo/downloads/Django-4.0.0-py3-none-any.whl

Verify no constraints file was created:

.. code-block:: bash

   ls work-dir/constraints.txt
   # Expected: file does not exist
