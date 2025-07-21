Building Pre-release Versions
=============================

By default, fromager ignores pre-release versions (alpha, beta, release candidate) when resolving package dependencies.
Versions with ``a``, ``b``, or ``rc`` components are only considered when explicitly requested.

This behavior follows Python packaging standards and ensures that stable versions are preferred unless pre-release versions are specifically needed.

Pre-release detection is handled on a package-by-package basis. This means you can mix stable and pre-release requirements in the
same build - some packages can use stable versions while others use pre-release versions.
This flexibility is useful when you need to test with a pre-release version of one specific package without affecting the rest of your dependency tree.

There are two ways to include pre-release versions in your builds:

Method 1: Include Pre-release in Requirements
---------------------------------------------

You can specify pre-release versions directly in your requirement specification by including the pre-release version in the version specifier:

.. code-block:: console

   $ fromager bootstrap "mypackage>=1.0a1"

This tells fromager that pre-release versions are acceptable for this package, and it will consider alpha versions ``1.0a1`` and later.

**Examples:**

.. code-block:: console

   # Build a specific pre-release version
   $ fromager bootstrap "django==4.2.0b1"

   # Allow any pre-release version above a threshold
   $ fromager bootstrap "numpy>=1.25.0rc1"

   # Mix stable and pre-release requirements
   $ fromager bootstrap "requests>=2.28.0" "django==4.2.0b1"

Method 2: Use Constraints File
------------------------------

Alternatively, you can enable pre-release versions through a constraints file.

Create a constraints file (e.g., ``constraints.txt``) with the pre-release version:

.. code-block:: text

   mypackage==1.0rc3

Then run fromager with the constraints file:

.. code-block:: console

   $ fromager --constraints-file constraints.txt bootstrap mypackage

**Example with conflicting stable requirement:**

If you have a requirement that specifies a version range but want to use a pre-release within that range:

.. code-block:: text
   :caption: constraints.txt

   flit-core==2.0rc3

.. code-block:: console

   $ fromager --constraints-file constraints.txt bootstrap "flit-core<2.0.1"

Even though the requirement ``flit-core<2.0.1`` would normally resolve to the latest stable version (e.g., ``2.0``), the constraint forces the use of the pre-release version ``2.0rc3``.
