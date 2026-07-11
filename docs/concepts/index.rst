Concepts
========

Understanding how fromager works under the hood.

Key Topics
----------

These guides explain the fundamental concepts and design principles behind fromager:

* **Architecture Overview** - Major subsystems, data flow, extension points, and key data structures
* **Bootstrap vs Build Modes** - Understand the difference between recursive discovery (bootstrap) and single-package builds (build)
* **Bootstrapper Architecture** - Phase pipeline, class hierarchy, and interaction model of the bootstrap engine
* **Resolver Architecture** - Resolution strategies, provider hierarchy, version filtering, and per-package configuration
* **Hooks and Overrides** - The two plugin systems: per-package overrides and global hooks
* **Package Settings** - Settings loading, merge order, and the ``PackageBuildInfo`` facade
* **Dependency Types** - Learn about build-system, build-backend, build-sdist, and install dependencies

.. toctree::
   :maxdepth: 1

   architecture-overview
   bootstrap-vs-build
   bootstrapper-architecture
   resolver-architecture
   hooks-and-overrides
   package-settings
   dependencies

Related Practical Guides
-------------------------

Apply these concepts with task-oriented guides:

* :doc:`/using` - Bootstrap and build mode usage
* :doc:`/how-tos/repeatable-builds` - Use build graphs for consistent builds
* :doc:`/how-tos/graph-commands/index` - Analyze dependency graphs
* :doc:`/customization` - Customize the build process

Reference Material
------------------

* :doc:`/reference/glossary` - Definitions of key terms
* :doc:`/reference/files` - Build order and graph file formats
