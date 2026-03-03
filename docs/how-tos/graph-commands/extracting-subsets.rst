Extracting Graph Subsets
========================

The ``fromager graph subset`` command extracts a focused subgraph containing only the dependencies and dependents of a specific package. This is useful for understanding the impact scope of a particular package, debugging specific dependency issues, or creating smaller, more manageable graphs for analysis.

Basic Usage
-----------

To extract a subset graph for a specific package:

.. code-block:: bash

   fromager graph subset <graph-file> <package-name>

Example
-------

Using the example graph file from the e2e test, let's extract a subset for the ``keyring`` package:

.. code-block:: bash

   fromager graph subset e2e/build-parallel/graph.json keyring

This command will output a JSON graph containing:

- The ``keyring`` package itself
- All packages that depend on ``keyring`` (dependents)
- All packages that ``keyring`` depends on (dependencies)
- The ROOT node if ``keyring`` is a top-level dependency

The resulting subset will include packages like:

- ``keyring==25.6.0`` (the target package)
- ``imapautofiler==1.14.0`` (depends on keyring)
- ``jaraco-classes==3.4.0`` (keyring dependency)
- ``jaraco-context==6.0.1`` (keyring dependency)
- ``jaraco-functools==4.1.0`` (keyring dependency)
- And their transitive dependencies

Version Filtering
-----------------

You can limit the subset to a specific version of the target package using the ``--version`` flag:

.. code-block:: bash

   fromager graph subset e2e/build-parallel/graph.json setuptools --version 80.8.0

This is particularly useful when dealing with packages that have multiple versions in the graph, allowing you to focus on the relationships of a specific version.

File Output
-----------

Save the subset graph to a file instead of printing to stdout:

.. code-block:: bash

   fromager graph subset e2e/build-parallel/graph.json jinja2 -o jinja2-subset.json

The output file will be in the same JSON format as the original graph file and can be used as input to other ``fromager graph`` commands.

Use Cases
---------

**Debugging Dependency Issues**
  When a specific package is causing build problems, extract its subset to focus on just the relevant dependencies without the noise of the full graph.

**Impact Analysis**
  Before upgrading or removing a package, understand what other packages would be affected by examining its dependents.

**Creating Focused Build Graphs**
  Generate smaller graphs for specific components of your application, making it easier to understand and manage complex dependency trees.

**Documentation and Communication**
  Create focused dependency diagrams for specific packages when documenting or explaining system architecture to team members.

**Performance Optimization**
  When working with very large dependency graphs, extract subsets to improve performance of analysis tools and reduce memory usage.

Example Workflow
----------------

Here's a typical workflow for investigating a package's dependencies:

.. code-block:: bash

   # Extract subset for a problematic package
   fromager graph subset my-project-graph.json problematic-package -o debug-subset.json

   # Visualize the subset
   fromager graph to-dot debug-subset.json -o debug-subset.dot
   dot -Tpng debug-subset.dot -o debug-subset.png

   # Analyze why specific dependencies appear
   fromager graph why debug-subset.json some-unexpected-dependency

This workflow helps you quickly isolate and understand issues within a complex dependency tree.

Output Format
-------------

The subset command preserves the original graph structure and format. The output is a valid dependency graph that:

- Maintains all edge relationships between included nodes
- Preserves requirement specifications and constraint information
- Can be used as input to other graph commands
- Is compatible with existing fromager workflows

Error Handling
--------------

The command will report an error if:

- The specified package is not found in the graph
- The specified version of a package is not found
- The graph file is invalid or corrupted

Example error output:

.. code-block:: bash

   $ fromager graph subset e2e/build-parallel/graph.json nonexistent-package
   Error: Package nonexistent-package not found in graph
