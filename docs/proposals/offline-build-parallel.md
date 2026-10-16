# Offline wheel builds from prepared artifacts

- Author: Sean Pryor
- Created: 2026-10-04
- Status: Draft

## What

Add an opt-in `--offline` mode to `build-parallel`. It consumes a dependency
graph and the prepared artifacts from an earlier bootstrap run to build wheels
without repeating source acquisition or source-preparation work.

## Why

Preparing source distributions and their build environments can require network
access and package-specific hooks. Repeating those steps in every wheel-build
environment adds work and prevents builds from running in environments with no
network access.

Bootstrap already produces the graph and working files needed to separate
preparation from wheel building. An offline build mode lets operators prepare
those inputs once, then reuse them in a restricted build environment.

Separating preparation from building is the intended split between bootstrap
and the build commands
([#995](https://github.com/python-wheel-build/fromager/issues/995)); the
build steps doing any preparation work at all is leftover coupling. The mode
is opt-in to preserve the existing one-step behavior, but it is meant to
become the default, and eventually the only, behavior of the build commands.

## Goals

- Reuse an existing dependency graph, prepared source tree, build metadata,
  source distribution, and build environment.
- Reuse local wheels for packages that are already built or configured as
  pre-built.
- Skip `download_source`, `prepare_source`, `prepare_build_environment`, and
  `build_sdist` when `--offline` is enabled.
- Fail with a package-specific error when a required local artifact is missing,
  without falling back to a remote server.
- Preserve dependency ordering and the normal wheel-building outputs.

## Non-goals

- Creating or exporting a portable bootstrap bundle. This proposal covers
  consuming an existing prepared workspace.
- Resolving package versions or regenerating the dependency graph during the
  offline build.
- Guaranteeing that arbitrary package build scripts cannot access the
  network. Network isolation remains a property of the build environment.
- Defining artifact digests, provenance, or a cross-host transfer format.

## Related issues

This proposal is partial work toward
[#995](https://github.com/python-wheel-build/fromager/issues/995) and
[#797](https://github.com/python-wheel-build/fromager/issues/797), the
broader goal of fully separating dependency discovery from building, and
does not close either issue.

- **Two-stage build** ([#995](https://github.com/python-wheel-build/fromager/issues/995),
  [#797](https://github.com/python-wheel-build/fromager/issues/797)):
  offline mode gives the build commands a way to avoid preparation work,
  but they still perform that work by default, and neither a dedicated
  `prepare` command nor a defined transferable workspace layout is part
  of this proposal.
- **Discovery fallback** ([#996](https://github.com/python-wheel-build/fromager/issues/996)):
  offline mode never reaches the fallback to PEP 517 discovery hooks
  because it reuses the prepared build environments. Eliminating that
  fallback for online builds remains open.
- **Sdist as build input** ([#1311](https://github.com/python-wheel-build/fromager/issues/1311),
  [#696](https://github.com/python-wheel-build/fromager/issues/696)):
  offline mode keeps building from the retained source tree, with the
  prepared sdist as a required artifact. The expectation that every
  package is buildable from its own sdist relies on the packaging best
  practices described in #696. Building the wheel from the unpacked
  downstream sdist instead remains follow-up work; the workspace already
  retains the sdist either way.
- **Git source resolvers** ([#1205](https://github.com/python-wheel-build/fromager/issues/1205),
  [#1206](https://github.com/python-wheel-build/fromager/issues/1206)):
  offline mode depends on bootstrap producing source trees and sdists, so
  packages using the git-clone source resolvers need that preparation
  work to land first. Offline mode does not change how sources are
  prepared.
- **Build-tag acceptance** ([#1360](https://github.com/python-wheel-build/fromager/issues/1360)):
  offline mode applies the same wheel acceptance rules as an online
  build, so it takes no position on what those rules should be.
  Consolidating them remains follow-up work.

## How

A workflow prepares a package graph and workspace by running
`fromager --no-cleanup bootstrap --sdist-only`, then runs
`build-parallel --offline` against that graph and workspace. For each graph
node, Fromager reuses a suitable local wheel when available. Otherwise, it
builds the wheel from the prepared source tree using the existing build
environment. Packages configured as pre-built require a local pre-built
wheel. Packages whose wheels were already built during preparation, such as
build requirements, are satisfied from the local wheel repository.

Every package is expected to be buildable from its own sdist; a package that
cannot be is a packaging bug. Offline mode reuses the prepared source tree to
avoid repeating the preparation work, and the prepared sdist remains a
required artifact for each node.

Offline mode skips the four source and environment preparation phases listed
above and does not use external source or wheel servers. It still runs the
wheel build and its applicable post-build hooks. The workspace therefore needs
to contain the prepared source, metadata, source distribution, and build
environment for each package that must be built from source.

The graph and workspace should come from the same preparation run and build
context. Fromager checks package and version metadata where available and
stops with a clear error if a required artifact is missing or inconsistent; it
does not retry the skipped preparation steps online.

The prepared sdist for a node is located by its expected filename, including
any package naming hooks, falling back to the name and version parsed from
the files present. The prepared source tree is validated against its build
metadata. Sdist filenames carry no build tag, so prepared sdists from
different runs with the same name and version are not distinguished from each
other; verifying content digests is a non-goal.

## Preparing the workspace

The preparation run is `fromager --no-cleanup bootstrap --sdist-only`,
started from a clean output directory so that the offline inputs are exactly
what the preparation produces and nothing depends on leftover state. Both
options are required:

- `--sdist-only` prepares sdists and build environments without building the
  remaining wheels, so there is work left for the offline build.
- `--no-cleanup` keeps the prepared source trees and build environments in
  the work directory. By default Fromager removes each package's source tree
  as soon as its build metadata is recorded. A workspace prepared without
  `--no-cleanup` has no source trees to reuse, so every from-source package
  fails with an "offline mode requires prepared source" error.

`bootstrap-parallel --offline` consumes the graph and workspace in place; it
is the equivalent of the preparation bootstrap followed by
`build-parallel --offline`.

The preparation run and the offline build are coupled in three ways:

- **Package settings.** Expected wheel build tags are computed from the
  package settings changelogs and hooks in both phases, so both phases must
  use the same settings directory and overrides. A local wheel whose build
  tag no longer matches the settings is ignored, and the build then fails if
  no prepared source exists for the package.
- **Constraints.** Version resolution happens during preparation and the
  resolved versions are recorded in the graph, so the offline build does not
  need constraints and does not consult them. Fromager reads every
  `--constraints-file` argument, including remote URLs, when it starts and
  before any command runs, so the offline invocation must reference local
  files only, or pass no constraints at all.
- **Build image.** Build environment directory names embed the interpreter
  version, and the `python` inside each environment is a symlink to the base
  interpreter that created it. The offline build must run in the same build
  image (or an image with the same interpreter at the same path) as the
  preparation run. The offline phase also invokes the `uv` and `wheel`
  command line tools.

## Limitations

`--offline` prevents Fromager from fetching sources, preparing them, creating
build environments, or building source distributions during `build-parallel`.
It does not prevent a package's wheel-build hook or build tool from attempting
network access. Plugins configured with `network_isolation: false` may still
attempt remote access, and tools such as Bazel may fetch dependencies during
the wheel build. Strict network isolation must be applied by the container or
build environment.

The offline build does not consult remote wheel caches or package indexes.
Each graph node is still checked against the local wheel repository, with the
same reuse rules as an online build, to decide whether it needs to be built.
A wheel that exists only remotely, including in the index the built wheels
will be published to, can only be reused by populating the local wheel
repository during preparation.

Offline mode does not invoke the package hooks for the phases it skips
(source download and preparation, build environment setup, and sdist
building). The `build_wheel` hook and the prebuilt-wheel and post-build hooks
still run. The plugin interface for distinguishing bootstrap behavior from
build behavior is unchanged; refining it is follow-up work.

## Example

```bash
# Preparation, with network access: resolves versions, prepares sdists,
# source trees, and build environments.
fromager --no-cleanup bootstrap --sdist-only 'stevedore==5.2.0'

# Offline wheel build: no external network access required.
fromager build-parallel --offline work-dir/graph.json
```
