# Global hook for build-system dependency post-processing

- Author: Vikash Shaw
- Created: 2026-07-24
- Status: Proposed
- GitHub issue: [#1263](https://github.com/python-wheel-build/fromager/issues/1263)
- GitHub PR: [#1271](https://github.com/python-wheel-build/fromager/pull/1271)

## What

This proposal suggests adding `get_build_system_dependencies` as a new
global hook point under `fromager.hooks`, so that downstream projects
can register hooks to post-process the build-system dependencies list
for all packages without needing per-package plugins.

## Why

Fromager currently provides two extension mechanisms:

1. **Per-package plugins** (`fromager.project_overrides`): Override a
   hook for a single package. When present, the plugin replaces the
   default implementation entirely.

2. **Global hooks** (`fromager.hooks`): Run for every package. Currently
   support `post_build`, `post_bootstrap`, and `prebuilt_wheel`, which
   are event callbacks that fire after an action has completed.

Currently, no global hook runs during dependency resolution. When a
cross-cutting concern affects build dependencies for many packages, the
only option today is to write identical per-package plugins for each one.

### Motivating example

setuptools 81 removed `distutils.spawn(dry_run=...)` and
`remove_tree(dry_run=...)`. setuptools 82 removed `pkg_resources`
entirely. Many PyPI packages still reference these removed APIs in their
`setup.py`, causing build failures when Fromager resolves an uncapped
setuptools.

In one downstream project, this led to **22 identical per-package
plugins**, each scanning `setup.py` to detect removed API usage and
appending a setuptools version cap. Every time a new package hits the
same incompatibility, another identical plugin must be added. This does
not scale well.

A global hook would let downstream projects handle this with a single
hook registration instead.

### Why not `update_build_requires`?

Fromager's YAML settings support `update_build_requires` for statically
adding build dependencies. However, the setuptools cap is conditional
and depends on what APIs a given `setup.py` actually uses. A static YAML
entry would either over-constrain all packages or require per-package
entries, which has the same maintenance burden as plugins.

### Why a global hook rather than core logic?

Based on maintainer feedback, this kind of logic is better suited as an
opt-in hook rather than built into Fromager's core. Different downstream
projects may have different needs, and a hook keeps Fromager generic
while letting each project bring its own dependency-fixing logic.

## Goals

- Extend the existing `fromager.hooks` system with a
  `get_build_system_dependencies` hook point
- Allow multiple hooks to chain (output of one feeds into the next)
- Preserve backward compatibility with per-package plugins
- Follow the existing stevedore-based hook pattern

## Non-goals

- Adding setuptools-capping logic to Fromager core
- Replacing per-package plugins for packages with truly custom logic
- Adding global hooks for other dependency types at this time (those
  could follow later using the same pattern if there is interest)

## How

### Execution order

The hook would run inside `dependencies.get_build_system_dependencies()`,
after the per-package override (or default) returns and before marker
filtering:

```
1. Check for cached requirements file (early return if exists)
2. overrides.find_and_invoke()          <-- per-package plugin or default
3. hooks.run_get_build_system_dependencies_hooks()   <-- NEW
4. _filter_requirements()               <-- marker evaluation
5. Write requirements cache file
```

This means per-package plugins still produce the initial dependency
list, global hooks can then augment it, and marker filtering happens
last so hooks do not need to handle markers themselves. The result is
cached, so hooks run only once per package per build.

### Hook signature

```python
def get_build_system_dependencies(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    build_dir: pathlib.Path,
    requirements: list[str],
) -> list[str]:
    ...
```

The hook receives the current requirements list and must return a
(possibly modified) `list[str]`. When multiple hooks are registered,
they chain: each receives the previous hook's output. Execution order
follows stevedore's `HookManager` iteration order.

### Registration

Hooks are registered as entry points under the `fromager.hooks`
namespace, the same way `post_build` and other existing hooks work:

```toml
[project.entry-points."fromager.hooks"]
get_build_system_dependencies = "my_package.hooks:get_build_system_dependencies"
```

### Example hook

A minimal hook that appends a constraint:

```python
def get_build_system_dependencies(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    build_dir: pathlib.Path,
    requirements: list[str],
) -> list[str]:
    # Inspect sdist content and conditionally add constraints
    if needs_constraint(build_dir):
        return requirements + ["setuptools<82"]
    return requirements
```

## Interaction with existing mechanisms

| Mechanism | Scope | Relationship to global hooks |
| --- | --- | --- |
| `update_build_requires` (YAML) | Per-package, static | Runs during `prepare_source`, before this hook. |
| `remove_build_requires` (YAML) | Per-package, static | Same as above. |
| Per-package plugin | Per-package, dynamic | Runs first. Global hooks receive its output. |
| Cached `build-system-requirements.txt` | Per-package | If cache exists, function returns early. Hooks do not run. |
| **Global hooks (this proposal)** | All packages, dynamic | Runs after per-package plugin, before marker filtering. |


