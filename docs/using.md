# Using fromager

## Modes

Fromager has different modes for bootstrapping and production builds.
The bootstrap mode recursively processes all dependencies starting
from the requirements specifications given to determine what needs to
be built and what order to build it. The production build commands
separate these steps and avoid recursive processing so each step can
be performed in isolation.

## Bootstrapping

The `bootstrap` command

* Creates an empty package repository for
  [wheels](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)
* Downloads the [source
  distributions](https://packaging.python.org/en/latest/glossary/#term-Source-Distribution-or-sdist)
  for the input packages and places them under
  `sdists-repo/downloads/`.
* Recurses through the dependencies
  * Firstly, any build system dependency specified in the
    pyproject.toml build-system.requires section as per
    [PEP517](https://peps.python.org/pep-0517)
  * Secondly, any build backend dependency returned from the
    get_requires_for_build_wheel() build backend hook (PEP517 again)
  * Lastly, any install-time dependencies of the project as per the
    wheel's [core
    metadata](https://packaging.python.org/en/latest/specifications/core-metadata/)
    `Requires-Dist` list.
* As each wheel is built, it is placed in a [PEP503 "simple" package
  repository](https://peps.python.org/pep-0503/) under
  `wheels-repo/simple`.
* The order the dependencies need to be built bottom-up is written to
  `build-order.json`.

Wheels are built by running `pip wheel` configured so it will only
download dependencies from the local wheel repository. This ensures
that all dependencies are being built in the correct order.

By default `bootstrap` builds all wheels that are neither in the local nor
in the remote cache. The default behavior verifies that every wheel can be
built from sources. The option `--sdist-only` switches `bootstrap` into a
fast mode that does not build new wheel for `Requires-Dist` dependencies. The
mode is advised if you just need `build-order.json` and have platlib packages
that take a lot of time to compile.

### High-Level Bootstrap Process

For each package being bootstrapped, fromager follows these key steps:

1. **Version Resolution** - Determines the specific version to build based on:
   * Version constraints and requirements specifications
   * Previous bootstrap history (if available)
   * Available sources (PyPI, git repositories, or prebuilt wheels)

2. **Cache Checking** - Looks for existing wheels in multiple locations:
   * Local build cache (`wheels-repo/build/`)
   * Local download cache (`wheels-repo/downloads/`)
   * Remote wheel server cache (if configured)

3. **Source Preparation** (if no cached wheel found):
   * Downloads source distribution or clones git repository
   * Unpacks and applies any patches via overrides
   * Prepares the source tree for building

4. **Build Dependencies Resolution** - Recursively processes three types of dependencies:
   * **Build System** - Basic tools needed to understand the build (e.g., setuptools, poetry-core)
   * **Build Backend** - Additional dependencies returned by build backend hooks
   * **Build Sdist** - Dependencies specifically needed for source distribution creation

5. **Build Process** - Creates the distribution:
   * Builds source distribution (sdist) with any patches applied
   * Builds wheel from the prepared source (unless `--sdist-only` mode)
   * Updates the local wheel repository mirror

6. **Dependency Discovery** - Extracts installation dependencies from:
   * Built wheel metadata (preferred method)
   * Source distribution metadata (in `--sdist-only` mode)

7. **Recursive Processing** - Repeats the entire process for each discovered installation dependency

8. **Build Order Tracking** - Maintains dependency graph and build order in:
   * `build-order.json` - Sequential build order for production builds
   * `graph.json` - Complete dependency relationship graph

The process continues recursively until all dependencies are resolved and built,
ensuring a complete bottom-up build order where each package's dependencies are
built before the package itself.

### Bootstrap Options

#### Skip Constraints Generation

The `--skip-constraints` option modifies the bootstrap behavior to allow building collections with conflicting package versions:

```bash
fromager bootstrap --skip-constraints package1==1.0 package2==2.0
```

When this option is used:

* The `constraints.txt` file generation is bypassed
* Packages with conflicting version requirements can be built in the same run
* The dependency resolution and build order logic still applies to individual packages
* Other output files (`build-order.json`, `graph.json`) are generated normally

This option is useful for:

* Building large package indexes that may contain multiple versions
* Testing scenarios requiring conflicting package versions
* Creating wheel collections where pip-installability is not required

**Important:** The resulting wheel collection may not be installable as a coherent set using pip.

## Production Builds

Production builds use separate commands for the steps described as
part of bootstrapping, and accept arguments to control the servers
that are used for downloading source or built wheels.

Two commands support building wheels from source.

### The build command

The `build` command takes as input the distribution name and version
to build, the variant, and the URL where it is acceptable to download
source distributions. The server URL is usually a simple index URL for
an internal package index.

The outputs are one patched source distribution and one built wheel.

The process follows these steps:

1. **Version Resolution** - Determines the exact source to build:
   * Resolves the specified version against the provided source server
   * Locates the source distribution URL for the target version
   * Validates that the requested version is available

2. **Source Acquisition** - Downloads and prepares the source code:
   * Downloads source distribution from the specified server URL
   * Saves source distribution to the sdist repository
   * Logs source download location and metadata

3. **Source Preparation** - Prepares source for building:
   * Unpacks the downloaded source distribution
   * Applies any configured patches via overrides system
   * Handles source code modifications (vendoring, etc.)
   * Creates prepared source tree in working directory

4. **Build Environment Setup** - Creates isolated build environment:
   * Determines build system requirements
   * Installs build dependencies into the isolated environment

5. **Source Distribution Creation** - Builds patched sdist:
   * Creates new source distribution including any applied patches
   * Preserves modifications made during source preparation
   * Saves patched sdist to the sdist repo.

6. **Wheel Building** - Compiles the final wheel:
   * Uses prepared source and build environment
   * Applies any build-time configuration overrides
   * Compiles extensions and processes package files
   * Creates wheel in the wheels repo

7. **Post-Build Processing** - Finalizes the build:
   * Runs configured post-build hooks
   * Updates wheel repository mirror

The build command provides a focused, single-package build process suitable for
individual package compilation or integration into larger build systems.

### The build-sequence command

The `build-sequence` command processes a pre-determined build order file
(typically `build-order.json`) to build wheels in dependency order.

The outputs are patched source distributions and built wheels for each item in
the build-order file.

Unlike `build`, the `build-sequence` command is optimized to use a wheel cache
for any wheels that have already been built with the current settings.

For each package in the sequence:

1. **Build Order Reading** - Loads the build order file containing:
   * Package names and versions to build
   * Source URLs and types (PyPI, git, prebuilt)
   * Dependency relationships and constraints

2. **Build Status Checking** - Determines if building is needed:
   * Checks local wheel repository for existing builds
   * Checks remote wheel server cache (if configured)
   * Skips builds if wheel exists (unless `--force` flag used)
   * Validates build tags match expected values

3. **Prebuilt Wheel Handling** - For packages marked as prebuilt:
   * Downloads wheel from specified URL
   * Runs prebuilt wheel hooks for any post-download processing
   * Updates local wheel repository mirror

4. **Source-to-Wheel Build Process** - Identical to what the `build` command does, for packages requiring compilation:
   * **Source Download** - Fetches source distribution from configured server
   * **Source Preparation** - Unpacks source and applies patches/overrides
   * **Build Environment** - Creates isolated build environment with dependencies
   * **Sdist Creation** - Builds new source distribution with applied patches
   * **Wheel Building** - Compiles wheel from prepared source
   * **Post-build Hooks** - Runs any configured post-build processing

5. **Repository Management** - After each successful build:
   * Updates local wheel repository mirror
   * Makes wheels available for subsequent builds in the sequence
   * Ensures proper wheel server state for dependency resolution

6. **Summary Generation** - Upon completion:
   * Creates markdown and JSON summary reports
   * Categorizes results (new builds, prebuilt wheels, skipped builds)
   * Reports build statistics and platform-specific wheel counts

The build sequence ensures proper dependency order where each package's
dependencies are available before building the package itself, enabling reliable
and reproducible wheel creation.

### Step-by-step commands

Occasionally it is necessary to perform additional tasks between build
steps, or to run the different steps in different configurations (with
or without network access, for example). Using the `step` subcommands,
it is possible to script the same operations performed by the `build`
and `build-sequence` commands.

The `step download-source-archive` command finds the source
distribution for a specific version of a dependency on the specified
package index and downloads it. It will be common to run this step
with `pypi.org`, but for truly isolated and reproducible builds a
private index server is more robust.

The `step prepare-source` command unpacks the source archive
downloaded from the previous step and applies any patches (refer to
[customization](customization.md) for details about patching).

The `step prepare-build` command creates a virtualenv with the build
dependencies for building the wheel. It expects a `--wheel-server-url`
as argument to control where built wheels can be downloaded.

The `step build-sdist` command turns the prepared source tree into a
new source distribution ("sdist"), including any patches or vendored
code.

The `step build-wheel` command creates a wheel using the build
environment and prepared source, compiling any extensions using the
appropriate override environment settings (refer to
[customization](customization.md) for details about overrides).
