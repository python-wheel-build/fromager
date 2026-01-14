# Glossary

This glossary defines key terms used throughout fromager's documentation and codebase.

## A

### ABI Tag

The Application Binary Interface tag in a wheel filename that indicates binary compatibility (e.g., `cp311` for CPython 3.11). Part of the [wheel filename convention](#wheel).

## B

### Bootstrap

The primary mode of operation in fromager that recursively discovers and builds all dependencies for a set of top-level requirements. The `bootstrap` command downloads source distributions, resolves dependencies, and builds wheels in the correct order. See also: [Production Build](#production-build).

### Build Backend

The Python build tool that implements PEP 517/518 hooks to create distributions. Examples include `setuptools`, `flit_core`, `hatchling`, and `maturin`. Fromager calls the build backend's hooks to determine dependencies and build wheels.

### Build Environment

An isolated virtual environment created by fromager for building each package. Contains only the declared build dependencies, ensuring reproducible builds. Managed by the `BuildEnvironment` class.

### Build Order

The bottom-up sequence in which packages must be built so that each package's dependencies are available before it is built. Recorded in `build-order.json`.

### Build Tag

A numeric prefix added to fromager-built wheels (e.g., the `0` in `package-1.0.0-0-py3-none-any.whl`). Used to differentiate wheels built with different settings or patches while maintaining the same version number.

### Build-Time Dependencies

Dependencies required to build a package, not to run it. Includes [build-system](#build-system-dependencies), [build-backend](#build-backend-dependencies), and [build-sdist](#build-sdist-dependencies) dependencies.

### Build-System Dependencies

Packages specified in `pyproject.toml` under `[build-system].requires`. These are the basic tools needed to understand and initiate the build process (e.g., `setuptools`, `wheel`). See PEP 517.

### Build-Backend Dependencies

Additional dependencies returned by the build backend's `get_requires_for_build_wheel()` hook. These are determined dynamically after the build-system dependencies are installed.

### Build-Sdist Dependencies

Dependencies required specifically for creating a source distribution, returned by the build backend's `get_requires_for_build_sdist()` hook.

## C

### Cache

Local directories where fromager stores previously built or downloaded artifacts to avoid redundant work. Includes `wheels-repo/downloads/` for wheels and `sdists-repo/downloads/` for source distributions.

### Canonical Name

The normalized, lowercase form of a package name with all separators (hyphens, underscores, periods) converted to hyphens. Used for consistent identification across the ecosystem. Example: `Foo_Bar.baz` → `foo-bar-baz`.

### Constraints File

An input file (`constraints.txt`) that pins specific versions of packages without requiring them to be installed. Used to ensure consistent resolution across builds. Similar to pip's constraints mechanism.

### Collection

A set of wheels built together that represent a complete, installable set of packages for a specific use case. The output of a fromager bootstrap run.

## D

### Dependency Graph

A directed graph showing relationships between packages, including what depends on what and the type of each dependency. Stored in `graph.json` and used for visualization and analysis.

### Distribution Name

The official name of a Python package as it appears on PyPI or in requirements. May differ from the import name used in Python code.

## E

### Edge

In the dependency graph, a connection from one package to another representing a dependency relationship. Each edge includes the dependency type (`req_type`) and requirement specification (`req`).

### Entry Point

A mechanism for Python packages to advertise functionality to other packages. Fromager uses entry points for [override plugins](#override-plugin) (`fromager.project_overrides`) and custom CLI commands (`fromager.cli`).

## F

### Fromager

A tool for completely rebuilding a dependency tree of Python wheels from source. The name comes from the French word for cheesemaker, continuing Python's cheese-themed naming tradition.

### Fromager Hooks

Extension points that allow customization of fromager's behavior. Can be implemented as [override plugins](#override-plugin) for package-specific customization or as [process hooks](#process-hook) for build events.

## G

### Graph (graph.json)

An output file containing the complete dependency relationship information for all packages in a build. Maps each resolved package to its dependencies with type information. Used for visualization, analysis, and [repeatable builds](#repeatable-build).

## H

### Hook

A function that fromager calls at specific points during the build process to allow customization. See [Override Plugin](#override-plugin) and [Process Hook](#process-hook).

## I

### Install Dependencies

Runtime dependencies extracted from a built wheel's metadata (`Requires-Dist`). These are the packages needed to use the built package, not to build it.

## L

### Local Wheel Server

A simple HTTP server started by fromager during bootstrap to serve built wheels. Ensures that dependencies come only from packages built in the same run.

## N

### Normalized Name

See [Canonical Name](#canonical-name).

## O

### Override Name

A variant of the canonical name where hyphens are replaced with underscores. Used for settings files, patch directories, and override plugin names. Example: `foo-bar` → `foo_bar`.

### Override Plugin

A Python module registered via entry points that provides custom implementations of fromager's build hooks for a specific package. Allows complete customization of source acquisition, patching, and building.

### Overrides Directory

The directory structure containing [patches](#patch) and [settings files](#settings-file) for customizing package builds. Defaults to `overrides/`.

## P

### Patch

A diff file applied to source code before building. Stored in `overrides/patches/<package_name>/` or `overrides/patches/<package_name>-<version>/`. Can be variant-specific by placing in a subdirectory named after the variant.

### PEP 503

The Python Enhancement Proposal defining the Simple Repository API. Fromager creates a PEP 503-compliant package index in `wheels-repo/simple/`.

### PEP 517

The Python Enhancement Proposal defining the build backend interface. Fromager uses PEP 517 hooks to determine build dependencies and build packages.

### Platlib

Platform-specific packages containing compiled extensions (C, C++, Rust, etc.). These wheels are tagged with platform-specific ABI and platform tags.

### Prebuilt Wheel

A wheel obtained from an external source rather than built from source by fromager. Configured using the `pre_built: true` setting in a package's variant configuration.

### Process Hook

Hooks that run after build events (`post_build`, `prebuilt_wheel`, `post_bootstrap`). Registered via entry points in the `fromager.hooks` namespace. Used for tasks like publishing wheels to a package index.

### Production Build

Build commands (`build`, `build-sequence`) that operate on a pre-determined build order rather than discovering dependencies recursively. Designed for reproducible, isolated builds in production environments.

### Purelib

Pure Python packages containing no compiled extensions. These wheels use the `py3-none-any` tag and work on any platform.

## R

### Repeatable Build

A build that produces identical results when run with the same inputs. Fromager supports repeatable builds by using `graph.json` from a previous run via `--previous-bootstrap-file`.

### Requirement

A dependency specification that may include version constraints. Example: `requests>=2.28,<3.0`. Parsed using the `packaging` library's `Requirement` class.

### Requirements File

A text file listing packages to install or build, typically `requirements.txt`. Each line contains a requirement specification.

### Resolver

The component that determines specific versions of packages from requirement specifications. Fromager uses `resolvelib` and provides custom providers for different source types (PyPI, GitHub tags, GitLab tags).

### Runtime Dependencies

See [Install Dependencies](#install-dependencies).

## S

### Sdist (Source Distribution)

An archive containing package source code in a format suitable for building. Typically a `.tar.gz` file. Fromager downloads sdists from package indexes and can create modified sdists with patches applied.

### Sdists-Repo

The directory structure storing source distributions:
- `downloads/` — Original sdists downloaded from upstream
- `builds/` — Modified sdists created by fromager after patching

### Settings File

A YAML file in `overrides/settings/` that configures how a package is built. Named using the [override name](#override-name) (e.g., `torch.yaml`). Can specify download URLs, environment variables, build options, and variant-specific settings.

### Simple Index

See [PEP 503](#pep-503). A directory structure that serves as a Python package repository.

### Step Commands

Individual build operations (`step download-source-archive`, `step prepare-source`, `step build-wheel`, etc.) that can be run separately for fine-grained control over the build process.

## T

### Toplevel Dependency

A package explicitly requested by the user via command line or requirements file, as opposed to dependencies discovered transitively.

## V

### Variant

A named build configuration that customizes how packages are built. Used to support different target platforms, hardware accelerators, or feature sets. The default variant is `cpu`. Set via `--variant` or the `FROMAGER_VARIANT` environment variable.

## W

### Wheel

A built distribution format for Python packages (PEP 427). A `.whl` file is a ZIP archive with a specific naming convention: `{name}-{version}(-{build})-{python}-{abi}-{platform}.whl`. Fromager builds wheels from source and stores them in `wheels-repo/`.

### Wheels-Repo

The directory structure storing built wheels:
- `build/` — Temporary output directory during wheel building
- `downloads/` — Completed wheels (built and prebuilt)
- `prebuilt/` — Wheels downloaded as prebuilt
- `simple/` — PEP 503 package index serving the wheels

### Work Directory (work-dir)

The temporary directory where fromager performs build operations. Contains unpacked source trees, build logs, dependency requirement files, and output files like `build-order.json`, `graph.json`, and `constraints.txt`.

### WorkContext

The central object in fromager's codebase that holds configuration and state for a build run. Passed to hooks and build functions. Provides access to paths, settings, constraints, and build options.
