Understanding Multiple Package Versions in a Graph
==================================================

When building complex Python projects, you may encounter situations where
multiple versions of the same package appear in your dependency graph. The
``fromager graph explain-duplicates`` command helps you understand why this
happens and whether it represents a problem.

Basic Usage
-----------

To analyze multiple versions in your graph:

.. code-block:: bash

   fromager graph explain-duplicates e2e/build-parallel/graph.json

This command will scan the entire graph and report on any packages that have multiple versions present.

Understanding the Output
------------------------

The command output shows:

1. **Package name**: The name of the package with multiple versions
2. **Available versions**: All versions found in the graph
3. **Requirements analysis**: Which packages require which versions
4. **Compatibility assessment**: Whether a single version can satisfy all requirements

Example Output
--------------

Here's an example of what you might see:

.. code-block:: text

   setuptools
     80.8.0
       setuptools>=61.2 matches ['80.8.0']
         keyring==25.6.0
       setuptools>=61 matches ['80.8.0']
         setuptools-scm==8.3.1
       setuptools matches ['80.8.0']
         setuptools-scm==8.3.1
     * setuptools==80.8.0 usable by all consumers

This output tells us:

- ``setuptools`` version 80.8.0 is present in the graph
- Three different requirement specifications exist for setuptools
- All requirements can be satisfied by version 80.8.0
- No version conflicts exist

Interpreting Results
--------------------

Good Case: Single Compatible Version
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When you see output like:

.. code-block:: text

   * package-name==1.2.3 usable by all consumers

This means all packages that depend on this package can use the same version. This is the ideal situation.

Problem Case: Version Conflicts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When you see output like:

.. code-block:: text

   * No single version of package-name meets all requirements

This indicates a dependency conflict where different packages require incompatible versions of the same dependency.

Common Scenarios
----------------

Build vs Runtime Dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sometimes you'll see the same package required at different versions for build-time and runtime:

.. code-block:: text

   setuptools
     45.0.0
       setuptools<60 matches ['45.0.0']
         some-old-package==1.0.0
     65.0.0
       setuptools>=60 matches ['65.0.0']
         modern-package==2.0.0
   * No single version of setuptools meets all requirements

In this case, you might need to update the older package or use package overrides.

Transitive Dependencies
~~~~~~~~~~~~~~~~~~~~~~~

Multiple versions can appear when different top-level packages pull in different versions of the same transitive dependency.

Resolution Strategies
---------------------

When you find version conflicts:

1. **Update packages**: Try updating packages to newer versions that have compatible requirements
2. **Use constraints**: Create a constraints file to pin specific versions
3. **Package overrides**: Use fromager's override system to force specific versions
4. **Remove conflicting packages**: Consider if all dependencies are actually needed

Example Investigation Workflow
------------------------------

.. code-block:: bash

   # 1. Check for duplicates
   fromager graph explain-duplicates e2e/build-parallel/graph.json

   # 2. If conflicts found, investigate why specific packages are included
   fromager graph why e2e/build-parallel/graph.json problematic-package

   # 3. Check the full dependency chain
   fromager graph why e2e/build-parallel/graph.json problematic-package --depth -1

   # 4. Visualize to better understand the relationships
   fromager graph to-dot e2e/build-parallel/graph.json --output graph.dot
   dot -Tpng graph.dot -o dependency-analysis.png

This workflow helps you:

1. Identify which packages have version conflicts
2. Understand why conflicting packages are included
3. See the complete dependency chain causing conflicts
4. Visualize the relationships for better analysis

Best Practices
--------------

- Run ``explain-duplicates`` regularly during development to catch conflicts early
- Pay attention to build-system vs install requirements, as they often have different version constraints
- Use the ``why`` command to understand the source of unexpected version requirements
- Consider using dependency scanning tools in your CI/CD pipeline to detect new conflicts
