Building from a Git Repository
==============================

You can build a package by cloning a git repository specifying the URL as part
of the requirement when bootstrapping.

For example, if you want to build a package from the ``stevedore`` repository,
you can do the following:

.. code-block:: console

   $ fromager bootstrap stevedore @ git+https://github.com/openstack/stevedore.git

This will clone the ``stevedore`` repository and build the package from the
local copy.

Building from a specific version
--------------------------------

To build a package from a git repository with a specific version, you can use
the ``@`` syntax to specify the version.

.. code-block:: console

   $ fromager bootstrap stevedore @ git+https://github.com/openstack/stevedore.git@5.2.0

This will clone the ``stevedore`` repository at the tagg ``5.2.0`` and build the
package from the local copy.

.. important::

    Building from a git repository URL is a special case which bypasses all of
    fromager's resolver behavior (builtin and plugins) for the package. Other
    plugins and override settings, such as preparing the source, patching it,
    and building the wheel, are honored.

.. important::

   Git URL syntax is only supported in the top level requirements input file or
   on the command line. Packages may not express dependencies using git URLs.
