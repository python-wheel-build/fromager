Understanding Dependency Types
==============================

Fromager tracks 5 dependency types, grouped into build-time and runtime categories.

Requirement Types
-----------------

**Build-Time** (must be built before parent):

- ``build-system`` — From ``pyproject.toml`` ``[build-system].requires`` with a fallback to a default provider (see PEP 517)
- ``build-backend`` — Returned by Fromager hooks, which call PEP 517 hooks like ``get_requires_for_build_wheel`` by default
- ``build-sdist`` — Returned by Fromager hooks, which call PEP 517 hooks by default

.. note::

   Both backend and sdist requirements are built before a package can be built.

**Runtime** (processed after parent is built):

- ``toplevel`` — Packages specified via CLI or requirements file
- ``install`` — Runtime dependencies extracted from built wheel (``install_requires``)

Key Behavior
------------

**Build dependency fails** → Parent **cannot build**

**Install dependency fails** → Parent **may still build** (failure occurs at runtime)

Identifying in graph.json
-------------------------

Each edge shows ``req_type``:

.. code-block:: json

   {"req_type": "build-system", "req": "setuptools>=45"}
   {"req_type": "install", "req": "requests>=2.28"}

Use ``fromager graph to-dot --install-only`` to filter runtime-only dependencies.
