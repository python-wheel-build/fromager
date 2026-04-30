Proposal: Convert Bootstrapper from Recursive to Iterative
==========================================================

Problem
-------

The ``Bootstrapper`` class processes dependency trees using recursive calls.
When bootstrapping packages with deep or wide dependency graphs — especially
with ``--multiple-versions`` enabled — this hits Python's recursion depth limit
and causes stack overflow errors. The recursion occurs at two points: processing
install dependencies after building a package, and processing build
dependencies before building.

Proposed Solution
-----------------

Replace the recursive depth-first traversal with an iterative approach using an
explicit work stack. Each package version to bootstrap is represented as a
``BootstrapWorkItem`` dataclass that flows through five linear phases:

1. **START** — Add to dependency graph and check if already seen (early exit if so)
2. **EXTRACT_BUILD_DEPS** — Collect build dependencies and push them onto the stack
3. **BUILD_PACKAGE** — Build sdist and/or wheel, record in build order
4. **EXTRACT_INSTALL_DEPS** — Extract install dependencies and push onto the stack
5. **COMPLETE** — Clean up build directories

The LIFO stack ensures depth-first traversal order is preserved. Build
dependencies are pushed in reverse order so they pop in the correct sequence
(BUILD_SYSTEM before BUILD_BACKEND before BUILD_SDIST). Each dependency
completes all five phases before its parent continues to the next phase.

This pattern already exists in the codebase: ``dependency_graph.py`` and
``commands/graph.py`` both use stack-based DFS traversals.

Scope
-----

This is a pure refactoring — no behavior changes. The external interface
(``bootstrap()`` method signature, CLI flags, output files) remains identical.
All existing error handling modes (normal fail-fast, ``--test-mode``,
``--multiple-versions``) are preserved. Progress bar semantics are unchanged.

The change is limited to ``src/fromager/bootstrapper.py``. No other files
require modification. All existing tests must pass without changes.

Benefits
--------

- Eliminates recursion depth limits entirely (work stack lives on the heap)
- Handles arbitrarily deep and wide dependency graphs
- Improves debuggability with explicit state in work items
- Follows proven patterns already established in the codebase

Verification
------------

- All existing unit and e2e tests must pass unchanged
- Bootstrap output for the same inputs must be identical
- Performance should remain within 10% of the recursive version
- Rollback via ``git revert`` if issues are discovered post-merge
