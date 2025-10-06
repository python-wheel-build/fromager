Understanding Why a Package is in the Graph
============================================

The ``fromager graph why`` command helps you understand why a specific package
that is not in your input requirements list appears in the dependency graph.
This is useful for debugging unexpected dependencies and understanding the
dependency chain.

Basic Usage
-----------

To find out why a package is included in your build graph:

.. code-block:: bash

   fromager graph why <graph-file> <package-name>

Example
-------

Using the example graph file from the e2e test:

.. code-block:: bash

   fromager graph why e2e/build-parallel/graph.json setuptools

This will show you the dependency chain that led to ``setuptools`` being included in the graph, even though it's not in the top-level requirements.

Expected output:

.. code-block:: text

   setuptools==80.8.0
     * setuptools==80.8.0 is an build-system dependency of imapautofiler==1.14.0 with req setuptools
       * imapautofiler==1.14.0 is a toplevel dependency with req imapautofiler==1.14.0

Advanced Options
----------------

Filter by Version
~~~~~~~~~~~~~~~~~

To check why a specific version of a package is included:

.. code-block:: bash

   fromager graph why e2e/build-parallel/graph.json setuptools --version 80.8.0

Recursive Dependency Analysis
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To see the full dependency chain recursively:

.. code-block:: bash

   fromager graph why e2e/build-parallel/graph.json more-itertools --depth -1

This shows the complete path from the root to the package:

.. code-block:: text

   more-itertools==10.7.0
     * more-itertools==10.7.0 is an install dependency of jaraco-functools==4.1.0 with req more_itertools
       * jaraco-functools==4.1.0 is an install dependency of keyring==25.6.0 with req jaraco.functools
         * keyring==25.6.0 is an install dependency of imapautofiler==1.14.0 with req keyring>=10.0.0
           * imapautofiler==1.14.0 is a toplevel dependency with req imapautofiler==1.14.0

Filter by Requirement Type
~~~~~~~~~~~~~~~~~~~~~~~~~~~

To see only specific types of dependencies (e.g., only install dependencies):

.. code-block:: bash

   fromager graph why e2e/build-parallel/graph.json setuptools --requirement-type install

Available requirement types:
- ``install``: Runtime installation dependencies
- ``build-system``: Build system requirements
- ``toplevel``: Top-level requirements from your input

Understanding the Output
------------------------

The output format shows:

- **Package name and version**: The package you're investigating
- **Dependency type**: Whether it's an ``install``, ``build-system``, or ``toplevel`` dependency
- **Parent package**: Which package requires this dependency
- **Requirement specification**: The actual requirement string used

This helps you understand the complete dependency chain and identify whether dependencies are coming from build requirements or runtime requirements.
