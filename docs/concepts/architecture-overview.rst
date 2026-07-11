Architecture Overview
=====================

Fromager rebuilds complete dependency trees of Python wheels from
source.  This document maps the major subsystems and how they connect.

.. seealso::

   :doc:`bootstrap-vs-build` explains the two operating modes.
   :doc:`bootstrapper-architecture` details the bootstrap engine.
   :doc:`resolver-architecture` covers version resolution.
   :doc:`hooks-and-overrides` describes the two plugin systems.
   :doc:`package-settings` explains the settings layering.

Major Subsystems
----------------

.. code-block:: text

   ┌───────────────────────────────────────────────────────┐
   │                    CLI & Context                      │
   │         command parsing, WorkContext, settings        │
   └───────────────────────────┬───────────────────────────┘
                               │
                               ▼
   ┌───────────────────────────────────────────────────────┐
   │                  Bootstrap Engine                     │
   │        iterative DFS loop over phase pipeline         │
   │                                                       │
   │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │
   │   │ Resolution  │  │    Source   │  │     Build   │   │
   │   │ PyPI, graph │  │ Acquisition │  │   System    │   │
   │   │  git URLs   │  │  download,  │  │  isolated   │   │
   │   │             │  │ patch, Rust │  │   envs,     │   │
   │   │             │  │   vendor    │  │   wheels    │   │
   │   └─────────────┘  └─────────────┘  └─────────────┘   │
   └───────────────────────────┬───────────────────────────┘
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
   ┌──────────────────┐              ┌──────────────────┐
   │  Per-Package     │              │   Global Hooks   │
   │  Overrides       │              │ post_bootstrap,  │
   │                  │              │    post_build    │
   └──────────────────┘              └──────────────────┘

The **bootstrap engine** orchestrates the other subsystems.  For each
package it resolves a version, downloads the source, builds a wheel,
and recurses into dependencies.  **Resolution**, **source acquisition**,
and **build** are called as needed during each phase of the pipeline.

**Extension points** intercept the pipeline at specific steps, allowing
per-package overrides (e.g. custom download logic) and global hooks
(e.g. post-build notifications).

Data Flow
---------

A ``fromager bootstrap`` invocation flows through the subsystems in
this order:

.. code-block:: text

   requirements.txt
                               │
                               ▼
   ┌─ CLI & Context ───────────────────────────────────────┐
   │  parse args, load settings, create WorkContext        │
   └───────────────────────────┬───────────────────────────┘
                               │
                               ▼
   ┌─ Bootstrap Engine (iterative DFS) ────────────────────┐
   │                                                       │
   │  ┌─────────────┐   ┌─────────────┐                    │
   │  │   Resolve   │──►│  Download   │                    │
   │  │   version   │   │   source    │                    │
   │  └─────────────┘   └──────┬──────┘                    │
   │                           │                           │
   │                           ▼                           │
   │  ┌─────────────┐   ┌─────────────┐                    │
   │  │  Extract &  │◄──│    Build    │                    │
   │  │  recurse    │   │    wheel    │                    │
   │  │  into deps  │   │             │                    │
   │  └─────────────┘   └─────────────┘                    │
   │                                                       │
   └───────────────────────────┬───────────────────────────┘
                               │
                               ▼
                        ┌── Outputs ──┐
                        │ graph.json  │
                        │ build-order │
                        │ wheels/     │
                        │ constraints │
                        └─────────────┘

The ``build`` command uses the same source acquisition and build
subsystems but skips resolution and recursion -- it compiles a
single package given a name, version, and source URL.

Extension Points
----------------

Fromager has two plugin systems:

.. list-table::
   :header-rows: 1
   :widths: 25 35 40

   * - System
     - Scope
     - When it fires
   * - **Per-package overrides**
     - One package
     - At each pipeline step (download, build sdist, build wheel,
       dependency extraction, etc.)
   * - **Global hooks**
     - All packages
     - After specific events (``post_bootstrap``, ``post_build``,
       ``prebuilt_wheel``)

Per-package overrides replace the default implementation of a step for
a specific package.  Global hooks run in addition to the default logic
for every package.  See :doc:`hooks-and-overrides` for the full
breakdown.

Key Data Structures
-------------------

Four data structures flow between subsystems:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Structure
     - Role
   * - ``WorkContext``
     - Central configuration and state: directory paths, constraints,
       dependency graph, settings, and variant info.  Passed to every
       subsystem.
   * - ``DependencyGraph``
     - In-memory directed graph of all resolved dependencies.
       Serialized to ``graph.json``.  Thread-safe.
   * - ``PackageBuildInfo``
     - Per-package build configuration: environment variables, patches,
       resolver settings, and build options.  Derived from settings
       files.
   * - ``BuildEnvironment``
     - Isolated virtual environment for building one package.  Created
       per source build, cleaned up after completion.
