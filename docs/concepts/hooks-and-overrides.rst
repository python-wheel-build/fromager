Hooks and Overrides
===================

Fromager has two plugin systems that serve different purposes:
**per-package overrides** replace default behavior for a specific
package, while **global hooks** broadcast notifications after events
for every package.

.. seealso::

   :doc:`architecture-overview` maps the major subsystems.
   :doc:`/reference/hooks` documents each override hook's arguments and
   return values.  :doc:`/customization` covers global hooks with code
   examples.

Comparison
----------

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Aspect
     - Per-Package Overrides
     - Global Hooks
   * - **Scope**
     - One named package
     - Every package
   * - **Cardinality**
     - At most one override module per package
     - Multiple plugins per hook
   * - **Semantics**
     - Replaces the default implementation
     - Runs in addition to the default
   * - **Return value**
     - Used by the caller
     - None (fire-and-forget)
   * - **Typical use**
     - Custom download, build, or resolution logic
     - Publishing wheels, validation, logging

Per-Package Overrides
---------------------

An override module provides alternative implementations for specific
build steps.  Fromager looks up the module by the canonicalized package
name.  If the module defines the requested method, it is called instead
of the default; otherwise the default runs.

Override hooks cover resolution, source acquisition, building,
dependency extraction, and build environment customization.  Third-party
packages register overrides via the ``fromager.project_overrides``
entry-point group in their ``pyproject.toml``, mapping a package name to
a Python module.

See :doc:`/reference/hooks` for the complete list of hooks and their
arguments.

Global Hooks
------------

Global hooks are event callbacks that fire for every package.  All
registered plugins for a hook are called sequentially.  They cannot
alter the build result — they are purely side-effecting notifications.

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Hook
     - When it fires
   * - ``post_build``
     - After a wheel is built from source (not for prebuilt wheels)
   * - ``prebuilt_wheel``
     - After a prebuilt wheel is downloaded (not built from source)
   * - ``post_bootstrap``
     - After a package is bootstrapped, before its install dependencies
       are processed

Third-party packages register hooks via the ``fromager.hooks``
entry-point group in their ``pyproject.toml``, mapping a hook name to
a callable.

See :doc:`/customization` for examples and argument details.
