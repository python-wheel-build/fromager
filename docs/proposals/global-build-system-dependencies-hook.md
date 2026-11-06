# Settings-driven hook for build-system dependency post-processing

- Author: Vikash Shaw
- Created: 2026-07-24
- Status: Proposed
- GitHub issue: [#1263](https://github.com/python-wheel-build/fromager/issues/1263)
- Proposal PR: [#1272](https://github.com/python-wheel-build/fromager/pull/1272)

## What

This proposal suggests adding a configurable hook in the global settings
file that post-processes build-system dependencies for packages entering
the source-build dependency-resolution path. The hook is specified as a
dotted import path and loaded via Pydantic's `ImportString`, following
the same pattern as the proposed `build_tag_hook`
([wheel-build-tag-hook](wheel-build-tag-hook.md)).

## Why

Fromager currently provides two extension mechanisms:

1. **Per-package plugins** (`fromager.project_overrides`): Override a
   hook for a single package. When present, the plugin replaces the
   default implementation entirely.

2. **Global hooks** (`fromager.hooks`): Run for every package. Currently
   support `post_build`, `post_bootstrap`, and `prebuilt_wheel`, which
   are event callbacks that fire after an action has completed.

Currently, no mechanism exists to post-process build-system dependencies
across all packages. When a cross-cutting concern affects build
dependencies for many packages, the only option today is to write
identical per-package plugins for each one.

### Motivating example

setuptools 81 removed support for the `setup.py --dry-run` option and
changed some related distutils/setuptools signatures. setuptools 82
removed `pkg_resources` entirely. Many PyPI packages still reference
these removed APIs in their `setup.py`, causing build failures when
Fromager resolves an uncapped setuptools.

In one downstream project, this led to **22 identical per-package
plugins**, each scanning `setup.py` to detect removed API usage and
appending a setuptools version cap. Every time a new package hits the
same incompatibility, another identical plugin must be added. This does
not scale well.

### Why not `update_build_requires`?

Fromager's YAML settings support `update_build_requires` for statically
adding build dependencies. However, the setuptools cap is conditional
and depends on what APIs a given `setup.py` actually uses. A static YAML
entry would either over-constrain all packages or still require
per-package entries, which reduces but does not eliminate the maintenance
overhead.

## How

### Configuration

The hook is configured in the global settings file as a dotted import
path, using Pydantic's `ImportString` for validation and loading:

```yaml
build_system_dependencies_hook: "my_package.hooks:fix_build_deps"
```

When not set, no post-processing is applied and behavior is unchanged.

### Hook signature

```python
def fix_build_deps(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    build_dir: pathlib.Path,
    requirements: list[str],
) -> list[str]:
    ...
```

The hook receives the current build-system requirements as a `list[str]`
and must return a (possibly modified) `list[str]`.

Before calling the hook, Fromager materializes the `Iterable[str]`
returned by `overrides.find_and_invoke()` into a `list[str]`, so the
hook always receives a concrete list.

### Execution order

The hook runs inside `dependencies.get_build_system_dependencies()`,
after the per-package override (or default) returns and before marker
filtering:

```
1. Check for cached requirements file (early return if exists)
2. overrides.find_and_invoke()          <-- per-package plugin or default
3. build_system_dependencies_hook()     <-- NEW (if configured)
4. _filter_requirements()               <-- marker evaluation
5. Write requirements cache file
```

Per-package plugins still produce the initial dependency list. The hook
can then augment it. Marker filtering happens last, so the hook does
not need to handle markers. The result is cached, so the hook runs only
once per package per build.

### Error handling

If the hook raises an exception, the build for that package fails. This
matches the behavior of the existing per-package overrides.

### Cache invalidation

The cached `build-system-requirements.txt` is written after the hook
runs. If the hook is changed or removed after a previous build has
cached requirements, the cached file must be cleared for the change to
take effect. In practice, this means clearing the work directory between
builds when the hook configuration changes.

### Implementation

Two files would be modified in Fromager:

**`src/fromager/packagesettings/_settings.py`:**

Add `build_system_dependencies_hook` to `SettingsFile`:

```python
build_system_dependencies_hook: pydantic.ImportString | None = None
```

**`src/fromager/dependencies.py`:**

After `overrides.find_and_invoke()` returns, check if the hook is
configured and call it:

```python
orig_deps = overrides.find_and_invoke(...)
hook = ctx.settings.build_system_dependencies_hook
if hook is not None:
    orig_deps = hook(
        ctx=ctx,
        req=req,
        sdist_root_dir=sdist_root_dir,
        build_dir=pbi.build_dir(sdist_root_dir),
        requirements=list(orig_deps),
    )
deps = _filter_requirements(req, orig_deps)
```

### Example

A hook that auto-caps setuptools for packages using removed APIs:

```python
def fix_build_deps(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    sdist_root_dir: pathlib.Path,
    build_dir: pathlib.Path,
    requirements: list[str],
) -> list[str]:
    if needs_setuptools_cap(build_dir):
        return requirements + ["setuptools<82"]
    return requirements
```

Configured in the downstream project's settings:

```yaml
build_system_dependencies_hook: "my_package.hooks:fix_build_deps"
```

The hook could also be released as a standalone installable package so
any Fromager user can reference it by import path without writing hook
code themselves.

## Interaction with existing mechanisms

| Mechanism | Scope | Relationship |
| -- | -- | -- |
| `update_build_requires` (YAML) | Per-package, static | Runs during `prepare_source`, before this hook. |
| `remove_build_requires` (YAML) | Per-package, static | Same as above. |
| Per-package plugin | Per-package, dynamic | Runs first. The hook receives its output. |
| Cached `build-system-requirements.txt` | Per-package | If cache exists, function returns early. Hook does not run. |
| **Settings hook (this proposal)** | All packages, dynamic | Runs after per-package plugin, before marker filtering. |

## Alternatives considered

### Stevedore global hooks (PR [#1271](https://github.com/python-wheel-build/fromager/pull/1271))

An earlier approach proposed adding `get_build_system_dependencies` as
a new hook point under `fromager.hooks` using stevedore's `HookManager`.
This was rejected because stevedore hooks are designed as fire-and-forget
event listeners (they return nothing and execution order does not
matter). A hook that receives input and returns modified output is a
fundamentally different pattern that does not fit the `HookManager`
model.

### Core logic in Fromager (PR [#1264](https://github.com/python-wheel-build/fromager/pull/1264))

An earlier approach proposed adding setuptools detection logic directly
into `default_get_build_system_dependencies`. This would have required
zero downstream changes, but was rejected because it makes Fromager
opinionated about a specific problem. Different downstream projects have
different needs, and the maintainer preferred keeping Fromager generic
with an opt-in mechanism instead.
