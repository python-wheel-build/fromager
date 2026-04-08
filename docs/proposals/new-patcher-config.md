# New patching configuration

- Author: Christian Heimes
- Created: 2026-02-26
- Status: Open

## What

This enhancement document proposes a new approach to patch sources and wheel
metadata through declarative configuration. The new feature supplements
current features like patch files and plugin hooks.

## Why

Fromager supports patch files and modifications with Python plugins. Patch
files are limited, because they either apply to a single version or to all
versions of a package. Python plugins are harder to write and take more
effort.

Fromager already supports limited patching of `pyproject.toml` with the
package setting option `project_override`.

## Goals

- provide simple, extensible patching facilities with a declarative
  configuration approach
- support version-specific patching (e.g. patch build system requirements for
  `>=1.0,<1.0`).
- make common tasks like fixing sdist metadata (`PKG-INFO`) easier
- enable patching of wheel and sdist package metadata so users can pin
  installation requirements (`requires-dist`) to constraints. The feature is
  designed to pin Torch version to ensure `libtorch` ABI compatibility.

## Non-goals

- patch files will not be deprecated and removed. Patches are still useful
  and will be supported in the future.
- CPU architecture-specific and variant-specific patches won't be supported,
  They are considered a misfeature. Patches should be architecture-
  independent, so they can be pushed to upstream eventually.
- patching of installation requirements (`requires-dist`) beyond pinning to
  constraints. Dependency issues should be fixed in upstream projects.

## How

The new system will use a new top-level configuration key `patch`, which is
an array of patch operations. Each patch operation has a title, optional
version specifier, and an action like `replace-line`, `fix-pkg-info`, or
`pyproject-build-system`.

- The action name acts as a tag ([discriminated union](https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions)).
- The `title` is a human-readable description that explains the purpose of
  the operation.
- The optional field `when_version` can be used to limit the action,
  e.g. `>=1.0,<2.0`.
  > **NOTE**: `when_version` is not compatible with nightly builds.
- Some actions have a `ignore_missing` boolean flag. If an action has no
  effect, then it fails and stops the build unless `ignore_missing` is set.
- All file names are relative to `sdist_root_dir`.
- Most patch actions are executed in `prepare_source` phase. Actions that
  affect `requires-dist` are run in `get_install_dependencies_of_sdist`
  and after `build_wheel` hook.

### Example actions

At first, we will implement a few patch actions that will cover the most
common cases. In the future, we may add additional patch actions.

- The `replace-line` action replaces lines in one or more files.

- The `delete-line` action removes a line from one or more files.

- The `pyproject-build-system` action replaces the old `project_override`
  settings `update_build_requires` and `remove_build_requires`.

- The `fix-pkg-info` action addresses issues with sdist's `PKG-INFO` files,
  e.g. wrong metadata version.

- The `pin-requires-dist-to-constraint` action pins `requires-dist` in sdist
  and wheel metadata to the values of global constraints. The primary use
  case is Torch. If a package is built with Torch 2.10.0 constraint, then
  we want the wheel to depend on exactly `torch==2.10.0`.

```yaml
patch:
  - title: Comment out 'foo' requirement for version >= 1.2
    action: replace-line
    files:
      - 'requirements.txt'
    search: '^(foo.*)$'
    replace: '# \\1'
    when_version: '>=1.2'
    ignore_missing: true

  - title: Remove 'bar' from constraints.txt
    action: delete-line
    files:
      - 'constraints.txt'
    search: 'bar.*'

  - title: Fix PKG-INFO metadata and update metadata version
    action: fix-pkg-info
    metadata_version: '2.4'
    when_version: '<1.0'

  - title: Add missing setuptools to pyproject.toml
    action: pyproject-build-system
    update_build_requires:
      - setuptools

  - title: Pin Torch to global constraint
    action: pin-requires-dist-to-constraint
    requirements:
     - torch
```

### Deprecations

The old settings `project_override.update_build_requires` and
`project_override.remove_build_requires` will be deprecated and eventually
removed.
