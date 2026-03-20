How-tos
=======

Task-oriented guides for common workflows and customization scenarios.

Popular Guides
--------------

Quick links to frequently used guides:

* :doc:`containers` - Running fromager in containers (recommended approach)
* :doc:`bootstrap-constraints` - Pin versions for reproducible builds
* :doc:`graph-commands/using-graph-why` - Debug unexpected dependencies
* :doc:`repeatable-builds` - Ensure build reproducibility

Getting Started
---------------

Essential guides for initial setup and first builds.

.. toctree::
   :maxdepth: 1

   containers
   bootstrap-constraints

Building Packages
-----------------

Guides for building packages from various sources and configurations.

.. toctree::
   :maxdepth: 1

   build-from-git-repo
   repeatable-builds
   parallel
   build-web-server

Build Configuration
-------------------

Customize builds with overrides, variants, and version handling.

.. toctree::
   :maxdepth: 1

   pyproject-overrides
   multiple-versions
   pre-release-versions

Analyzing Builds
----------------

Understand and debug dependency graphs and build issues.

.. toctree::
   :maxdepth: 1

   graph-commands/index

See Also
--------

* :doc:`/customization` - Comprehensive guide to customization options
* :doc:`/reference/config-reference` - Configuration reference
* :doc:`/reference/hooks` - Override plugins and hooks
