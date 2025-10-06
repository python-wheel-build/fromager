Graph Command Examples
======================

This section provides examples and documentation for using fromager's graph analysis commands to explore dependency graphs produced by builds.

All examples use the sample graph file ``e2e/build-parallel/graph.json`` which contains the dependency graph for building the ``imapautofiler`` package.

.. toctree::
   :maxdepth: 1
   :glob:

   [uvw]*

Overview of Graph Commands
--------------------------

The ``fromager graph`` command group provides several subcommands for analyzing dependency graphs:

- ``why``: Understand why a package appears in the dependency graph
- ``to-dot``: Convert graph to DOT format for visualization with Graphviz
- ``explain-duplicates``: Analyze multiple versions of packages in the graph
- ``to-constraints``: Convert graph to constraints file format
- ``migrate-graph``: Convert old graph formats to the current format

These tools help you understand complex dependency relationships, debug unexpected dependencies, and create visual representations of your build requirements.
