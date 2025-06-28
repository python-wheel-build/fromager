Using Constraints to Build Collections
======================================

Constraints are a way to specify the versions of packages that should be used
when building a collection. They are useful when you want to specify a version
of a package other than the default (usually the latest version).

Because several commands in fromager use constraints, you pass them to the base
command using the ``--constraints-file`` option.

For example, if you want to bootstrap a package that requires ``setuptools``
and you want to avoid a breaking change in ``setuptools`` you can create a
constraints file that tells fromager to avoid using the latest version of
``setuptools``:

.. code-block:: text

   setuptools<80.0.0

Then you would run the following command:

.. code-block:: console

   $ fromager --constraints-file constraints.txt bootstrap my-package

This will use the constraints in the ``constraints.txt`` file to build
``my-package``.

Use the same constraints file with ``fromager build-sequence`` when building the
production packages.

.. code-block:: console

   $ fromager --constraints-file constraints.txt build-sequence ./work-dir/build-order.json

This will use the constraints in the ``constraints.txt`` file to build the
production packages for ``my-package``.
