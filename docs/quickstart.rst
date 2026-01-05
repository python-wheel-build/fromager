Quick Start
===========

This guide gets you from zero to your first wheel build in under 5 minutes.

Prerequisites
-------------

You'll need Python 3.11 or later and network access to download packages from PyPI.

Installation
------------

Install fromager using pip:

.. code-block:: console

   $ pip install fromager
   $ fromager --version
   fromager, version X.Y.Z

Your First Build
----------------

Let's build a simple package and its dependencies from source. We'll use
``stevedore``, a lightweight package with minimal dependencies.

Create a ``requirements.txt`` file with the package name:

.. code-block:: console

   $ echo "stevedore" > requirements.txt

Run the bootstrap command:

.. code-block:: console

   $ fromager bootstrap -r requirements.txt

   primary settings file: overrides/settings.yaml
   per-package settings dir: overrides/settings
   variant: cpu
   ...
   100%|████████████████████████████████████████| 3/3 [00:08<00:00,  2.67s/pkg]
   writing installation dependencies to ./work-dir/constraints.txt

Check your results:

.. code-block:: console

   $ ls wheels-repo/downloads/
   pbr-6.1.0-0-py2.py3-none-any.whl
   setuptools-75.1.0-0-py3-none-any.whl
   stevedore-5.3.0-0-py3-none-any.whl

You've built ``stevedore`` and its dependencies (``pbr``, ``setuptools``)
entirely from source. Fromager downloaded the source distributions from PyPI,
figured out the build and runtime dependencies, built each package in the
correct order, and created wheels in ``wheels-repo/downloads/``.

For a detailed explanation of the output files and directories, see
:doc:`files`.

Pinning Versions with Constraints
---------------------------------

For reproducible builds, use a constraints file to pin specific versions:

.. code-block:: console

   $ echo "stevedore==5.3.0" > constraints.txt
   $ fromager -c constraints.txt bootstrap -r requirements.txt

The ``-c`` option ensures fromager uses exactly the versions you specify.

Next Steps
----------

Now that you've seen fromager work with a simple package, you might want to:

* Learn to debug build failures with a more complex example in :doc:`getting-started`
* Customize builds with settings, patches, and variants in :doc:`customization`
* Check specific guides in :doc:`how-tos/index`
