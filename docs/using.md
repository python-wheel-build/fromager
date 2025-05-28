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
    wheel’s [core
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

### All-in-one commands

Two commands support building wheels from source.

The `build` command takes as input the distribution name and version
to build, the variant, and the URL where it is acceptable to download
source distributions. The server URL is usually a simple index URL for
an internal package index. The outputs are one patched source
distribution and one built wheel.

The `build-sequence` command takes a build-order file and the variant. The outputs are patched source
distributions and built wheels for each item in the build-order file.

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
