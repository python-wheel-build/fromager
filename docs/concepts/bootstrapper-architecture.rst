Bootstrapper Architecture
=========================

The bootstrap command uses an iterative depth-first loop to resolve and
build an entire dependency tree.  This document describes the phase
pipeline, class hierarchy, and interaction model at a high level.

.. seealso::

   :doc:`architecture-overview` maps the major subsystems.
   :doc:`bootstrap-vs-build` covers the difference between bootstrap and
   build modes.

Bootstrap Phase Flow
--------------------

Every package passes through a sequence of phases.  Source packages
traverse the full pipeline; prebuilt wheels skip the build phases.

.. code-block:: text

   RESOLVE ──► START ──► PREPARE_SOURCE ─┬─► PREPARE_BUILD ──► BUILD ─┐
                  │                      │                            │
                  │            (prebuilt)└────────────────────────────┤
                  │                                                   │
                  │                  ┌────────────────────────────────┘
                  │                  ▼
                  │          PROCESS_INSTALL_DEPS ──► COMPLETE
                  │
             (already seen) ──► drop

Each phase returns a list of new items to push onto the work stack.
Dependency-discovery phases (``PREPARE_SOURCE``, ``PREPARE_BUILD``,
``PROCESS_INSTALL_DEPS``) also emit ``RESOLVE`` items for newly
discovered dependencies, which drives the recursive traversal.

Phase Class Hierarchy
---------------------

All phases inherit from the ``Phase`` abstract base class, which defines
the contract every phase must satisfy:

- ``run(bt)`` — execute the phase logic; return new items for the stack.
- ``background_work(bt)`` — optionally return a callable for background
  I/O (used by ``Resolve`` and ``PrepareSource``).
- ``requires_exclusive_run`` — return ``True`` to drain the thread pool
  before running (used by ``Build`` for exclusive builds).

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Phase
     - Role
   * - ``Resolve``
     - Resolve available versions; fan out one ``Start`` per version
   * - ``Start``
     - Add to dependency graph; deduplicate already-seen packages
   * - ``PrepareSource``
     - Download source or prebuilt wheel; read build-system deps
   * - ``PrepareBuild``
     - Install build-system deps; discover backend and sdist deps
   * - ``Build``
     - Build sdist and/or wheel; update the local mirror
   * - ``ProcessInstallDeps``
     - Run post-bootstrap hooks; extract install deps; record build order
   * - ``Complete``
     - Clean up build directories (terminal phase)

Each phase wraps a ``WorkItem`` dataclass that accumulates per-package
state (resolved version, build environment, build result, etc.) as it
moves through the pipeline.

Bootstrapper and Phase Interaction
----------------------------------

The ``Bootstrapper`` class owns the work stack and thread pool.  It runs
an iterative DFS loop:

.. code-block:: text

   ┌─────────────────────────────────────────────────────┐
   │                  Bootstrapper Loop                  │
   │                                                     │
   │  while stack:                                       │
   │      item = stack.pop()                             │
   │                                                     │
   │      if item.requires_exclusive_run:                │
   │          drain thread pool                          │
   │                                                     │
   │      new_items = item.run(self)                     │
   │                                                     │
   │      for each new_item in new_items:                │
   │          stack.push(new_item)                       │
   └─────────────────────────────────────────────────────┘

The ``Bootstrapper`` provides services that phases call back into during
``run()``: dependency graph updates, seen-set tracking, build-order
recording, and work-item creation for discovered dependencies.

Some phases (``Resolve`` and ``PrepareSource``) perform background I/O
in a thread pool.  When new items are pushed onto the stack, the
``Bootstrapper`` submits their ``background_work()`` immediately so I/O
overlaps with the main thread processing other items.  Each phase is
responsible for blocking on its own ``bg_future`` inside ``run()`` when
it needs the result.  Other phases run entirely on the main thread.
