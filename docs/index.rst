fromager
========

Fromager is a tool for completely re-building a dependency tree of
Python wheels from source.

The goals are to support guaranteeing

1. The `binary package
   <https://packaging.python.org/en/latest/glossary/#term-Built-Distribution>`__
   someone is installing was built from source in a known build environment
   compatible with their own environment
2. All of the package’s dependencies were also built from source -- any
   binary package installed will have been built from source
3. All of the build tools used to build these binary packages will
   also have been built from source
4. The build can be customized for the packager's needs, including
   patching out bugs, passing different compilation options to support
   build "variants", etc.

The basic design tenet is to automate everything with a default
behavior that works for most PEP-517 compatible packages, but support
overriding all of the actions for special cases, without encoding
those special cases directly into fromager.

Getting Started
---------------

Quick introduction and detailed walkthrough for new users.

.. toctree::
   :maxdepth: 2

   quickstart.rst
   getting-started.rst

Guides
------

Task-oriented guides for common workflows and customization.

.. toctree::
   :maxdepth: 2

   how-tos/index.rst
   customization.md
   using.md

Concepts & Explanation
----------------------

Understanding how fromager works and technical deep-dives.

.. toctree::
   :maxdepth: 2

   concepts/index.rst
   http-retry.md

Reference
---------

Technical reference for CLI, configuration, files, and terminology.

.. toctree::
   :maxdepth: 2

   reference/index.rst

Development
-----------

Contributing to fromager.

.. toctree::
   :maxdepth: 2

   develop.md
   proposals/index.rst

What's with the name?
---------------------

Python's name comes from Monty Python, the group of comedians. One of
their skits is about a cheese shop that has no cheese in stock. The
original Python Package Index (pypi.org) was called The Cheeseshop, in
part because it hosted metadata about packages but no actual
packages. The wheel file format was selected because cheese is
packaged in wheels. And
"`fromager <https://en.wiktionary.org/wiki/fromager>`__" (*fro mah jay*) is the French
word for someone who makes or sells cheese.
