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
