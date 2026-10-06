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

## How

A workflow prepares a package graph and workspace with the normal bootstrap
flow, then runs `build-parallel --offline` against that graph and workspace.
For each graph node, Fromager reuses a suitable local wheel when available.
Otherwise, it builds the wheel from the prepared source tree using the
existing build environment. Packages configured as pre-built require a local
pre-built wheel.

Offline mode skips the four source and environment preparation phases listed
above and does not use external source or wheel servers. It still runs the
wheel build and its applicable post-build hooks. The workspace therefore needs
to contain the prepared source, metadata, source distribution, and build
environment for each package that must be built from source.

The graph and workspace should come from the same preparation run and build
context. Fromager checks package and version metadata where available and
stops with a clear error if a required artifact is missing or inconsistent; it
does not retry the skipped preparation steps online.

## Limitations

`--offline` prevents Fromager from fetching sources, preparing them, creating
build environments, or building source distributions during `build-parallel`.
It does not prevent a package's wheel-build hook or build tool from attempting
network access. Plugins configured with `network_isolation: false` may still
attempt remote access, and tools such as Bazel may fetch dependencies during
the wheel build. Strict network isolation must be applied by the container or
build environment.

## Example

```bash
fromager build-parallel --offline graph.json
```
