# New patcher configuration

- Author: Christian Heimes
- Created: 2026-02-26
- Status: Open

## What

This enhancement document proposal a new approach to patch sources and wheel
metadata through declarative configuration.

## Why

TODO

## Goals

- provide simple patching facilities with a declarative configuration approach
- support version-specific patching (e.g. patch build system requirements for
  `>=1.0,<1.0`).
- make common tasks like fixing sdist metadata (`PKG-INFO`) easier
- add patching of wheel and sdist package metadata to remove or modify
  installation requirements (`requires-dist` field).

## Non-goals

- Patch files will not be deprecated and removed. Patches are still useful
  and will be supported in the future.
- CPU architecture-specific patches won't be supported, because they are a
  misfeature. Patches will be

## How

The new system will use a new top-level configuration key `patch`, which is
an array of patch operations. Each patch operation has a title, optional
version specifier, and an action like `replace-line`, `fix-pkg-info`, or
`pyproject-build-system`.

- The action name acts as a tag ([discriminated union](https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions)).
- The `title` is a human-readable description that explains the purpose of
  the operation.
- The optional field `when_version` can be used to limit the action,
   e.g. `>=1.0,<1.0`.
   > **NOTE**: `when_version` is not compatible with nightly builds.
- Some actions have a `ignore_missing` boolean flag. If an action has no
  effect, then it fails and stops the build unless `ignore_missing` is set.

Example:

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
  
  - title: Remove 'somepackage' installation requirement
    action: remove-install-requires
    requirement: somepackage

  - title: Fix PKG-INFO metadata version
    action: fix-pkg-info
    metadata_version: '2.4'
    when_version: '<1.0'
  
  - title: Add missing setuptools to pyproject.toml
    action: pyproject-build-system
    update_build_requires:
      - setuptools
  
   - title: Update Torch install requirement to version in build env
    action: pin-install-requires-to-build
    requirement: torch
```

### Actions

All file names are relative to `sdist_root_dir`.

- The `replace-line` action replaces lines in one or more files.

- The `delete-line` action removes a line from one or more files.

- The `pyproject-build-system` action replaces the old `project_override`
  settings `update_build_requires` and `remove_build_requires`.

- The `remove-install-requires` action removes a `requires-dist` entry from
  sdist and wheel installation requirements. The requirement is matched by
  name-only or by full requirement (including specifier set and markers).

- The `pin-install-requires-to-build` pins `requires-dist` in sdist
  and wheel metadata to the exact version in the build environment. The
  primary use case is Torch. If a package is build with Torch 2.9.1, then
  we want the wheel to depend on exactly `torch==2.9.1`.

### Deprecations

The old settings `project_override.update_build_requires` and
`project_override.remove_build_requires` will be deprecated and eventually
removed.
