# Customizing parts of the package build process

Fromager support customizing most aspects of the build process,
including acquiring the source, applying local patches, passing
arguments to the build, and providing a custom build command.

## Variants

It is frequently necessary to build the same packages in different
ways, especially for binary wheels with code compiled for different
operating systems or hardware architectures. In fromager, the sets of
build configuration options for each scenario is called a "variant".

The default variant is `cpu`, to differentiate from variants for
hardware accelerators.

A variant name can be any string, but since the variant name shows up
in filesystem paths it is often easier to avoid including whitespace.

Set the variant using the `--variant` command line option or the
`FROMAGER_VARIANT` environment variable (for ease of use in
containers).

## Build environment variables

Most python packages with configurable builds use environment variables to pass
build parameters. The environment variables set when `fromager` runs are passed
to the build process for each wheel. Sometimes this does not provide sufficient
opportunity for customization, so `fromager` also supports setting build
variables for each package using environment files. The `--envs-dir` command
line argument specifies a directory with environment files for passing variables
to the builds. The default is `overrides/envs`.

(canonical-distribution-names)=
Environment files are named using the [canonical distribution
name](#canonical-distribution-names) and the suffix `.env`.

Settings common to all variants of a given package can be placed in an
environment file at the root of the `--envs-dir`.

The most common reason for passing different environment variables is to support
different build variants, such as to enable different hardware accelerators.
Therefore, the environment file directory is organized with a subdirectory per
variant. Settings in the variant-specific file override and extend settings in
the base directory.

```console
$ tree overrides/envs/
overrides/envs/
├── flash_attn.env
├── vllm.env
├── cpu
│   └── vllm.env
├── cuda
│   ├── flash_attn.env
│   └── llama_cpp_python.env
└── test
    └── testenv.env
```

Environment files use shell-like syntax to set variables, with the
variable name followed by `=` and then the variable value. Whitespace
around the 3 parts will be ignored, but whitespace inside the value is
preserved. It is not necessary to quote values, and quotes inside the
value will be passed through.

Environment files support simple parameter expansions `$NAME` and
`${NAME}`. Values are taken from previous lines, then process environment.
Sub shell expression `$(cmd)` and extended parameter expansions like
`${NAME:-default}` are not implemented.

```console
$ cat overrides/envs/cuda/llama_cpp_python.env
LLAMA_NATIVE=off
CMAKE_ARGS=-DLLAMA_CUBLAS=on -DCMAKE_CUDA_ARCHITECTURES=all-major -DLLAMA_NATIVE=${LLAMA_NATIVE}
CFLAGS=-mno-avx
FORCE_CMAKE=1
```

## Patching source

The `--patches-dir` command line argument specifies a directory containing
patches to be applied after the source code is in place and before evaluating
any further dependencies or building the project. The default directory is
`overrides/patches`.

Patch files should be placed in a subdirectory matching the source directory
name and use the suffix `.patch`. The filenames are sorted lexicographically, so
any text between the prefix and suffix can be used to ensure the patches are
applied in a specific order.

Patches are applied by running `patch -p1 filename` while inside the root of the
source tree.

```console
$ ls -1 overrides/patches/*
clarifai-10.2.1/fix-sdist.patch
flash_attn-2.5.7/pyproject-toml.patch
jupyterlab_pygments-0.3.0/pyproject-remove-jupyterlab.patch
ninja-1.11.1.1/wrap-system-ninja.patch
pytorch-v2.2.1/001-remove-cmake-build-requirement.patch
pytorch-v2.2.1/002-dist-info-no-run-build-deps.patch
pytorch-v2.2.1/003-fbgemm-no-maybe-uninitialized.patch
pytorch-v2.2.1/004-fix-release-version.patch
pytorch-v2.2.2/001-remove-cmake-build-requirement.patch
pytorch-v2.2.2/002-dist-info-no-run-build-deps.patch
pytorch-v2.2.2/003-fbgemm-no-maybe-uninitialized.patch
pytorch-v2.2.2/004-fix-release-version.patch
xformers-0.0.26.post1/pyproject.toml.patch
```

Note: A legacy patch organization with the patches in the patches directory, not
in subdirectories, with the filenames prefixed with the source directory name is
also supported. The newer format, using subdirectories, is preferred because it
avoids name collisions between variant source trees.

## Override plugins

For more complex customization requirements, create an override plugin.

Plugins are registered using [entry
points](https://packaging.python.org/en/latest/specifications/entry-points/)
so they can be discovered and loaded at runtime. In `pyproject.toml`,
configure the entry point in the
`project.entry-points."fromager.project_overrides"` namespace to
link the [canonical distribution name](#canonical-distribution-names)
to an importable module.

```toml
[project.entry-points."fromager.project_overrides"]
flit_core = "package_plugins.flit_core"
pyarrow = "package_plugins.pyarrow"
torch = "package_plugins.torch"
triton = "package_plugins.triton"
```

The plugins are treated as providing overriding implementations of
functions with default implementations, so it is only necessary to
implement the functions needed to make it possible to build the
package.

### download_source

The `download_source()` function is responsible for resolving a
requirement and acquiring the source for that version of a
package. The default is to use pypi.org to resolve the requirement and
then download the sdist file for the package.

The arguments are the `WorkContext`, the `Requirement` being
evaluated, and the URL to the server where sdists may be found.

The return value should be a tuple containing the location where the
source archive file was written and the version that was resolved.

The function may be invoked more than once if multiple sdist servers
are being used. Returning a valid response prevents multiple
invocations.

```python
def download_source(ctx, req, sdist_server_url):
    ...
    return source_filename, version
```

### get_resolver_provider

(pypi.org)=
The `get_resolver_provider()` function allows an override to change
the way requirement specifications are converted to fixed
versions. The default implementation looks for published versions on a
Python package index. Most overrides do not need to implement this
hook unless they are building versions of packages not released to
[https://pypi.org](pypi.org).

For examples, refer to `fromager.resolver.PyPIProvider` and
`fromager.resolver.GitHubTagProvider`.

The arguments are the `WorkContext`, the `Requirement` being
evaluated, a boolean indicating whether source distributions should be
included, a boolean indicating whether built wheels should be
included, and the URL for the sdist server.

The return value must be an instance of a class that implements the
`resolvelib.providers.AbstractProvider` API.

The expectation is that a `download_source()` override will call
`sources.resolve_dist()`, which will call `get_resolver_provider()`,
and then the return value of the resolution will be passed back to
`download_source()` as a tuple of URL and version. The provider can
therefore use any value as the "URL" that will help it decide what to
download. For example, the `GitHubTagProvider` returns the actual tag
name in case that is different from the version number encoded within
that tag name.

```python
def get_resolver_provider(ctx, req, include_sdists, include_wheels, sdist_server_url):
    ...
```

The `GenericProvider` is a convenient base class, or can be instantiated
directly if given a `version_source` callable that returns an iterator of
version values as `str` or `Version` objects.

```python
from fromager import resolver

VERSION_MAP = {'1.0': 'first-release', '2.0': 'second-release'}

def _version_source(
        identifier: str,
        requirements: resolver.RequirementsMap,
        incompatibilities: resolver.CandidatesMap,
    ) -> typing.Iterable[Version]:
    return VERSION_MAP.keys()


def get_resolver_provider(ctx, req, include_sdists, include_wheels, sdist_server_url):
    return resolver.GenericProvider(version_source=_version_source, constraints=ctx.constraints)
```

### prepare_source

The `prepare_source()` function is responsible for setting up a tree
of source files in a format that is ready to be built. The default
implementation unpacks the source archive and applies patches.

The arguments are the `WorkContext`, the `Requirement` being
evaluated, the `Path` to the source archive, and the version.

The return value should be the `Path` to the root of the source tree,
ideally inside the `ctx.work_dir` directory.

```python
def prepare_source(ctx, req, source_filename, version):
    ...
    return output_dir_name
```

### expected_source_archive_name

The `expected_source_archive_name()` function is used to re-discover a
source archive downloaded by a previous step, especially if the
filename does not match the standard naming scheme for an sdist.

The arguments are the `Requirement` being evaluated and the version to
look for.

The return value should be a string with the base filename (no paths)
for the archive.

```python
def expected_source_archive_name(req, dist_version):
    return f'apache-arrow-{dist_version}.tar.gz'
```

### expected_source_directory_name

The `expected_source_directory_name()` function is used to re-discover
the location of a source tree prepared by a previous step, especially
if the name does not match the standard naming scheme for an sdist.

The arguments are the `Requirement` being evaluated and the version to
look for.

The return value should be a string with the name of the source root
directory relative to the `ctx.work_dir` where it was prepared.

```python
def expected_source_directory_name(req, dist_version):
    return f'apache-arrow-{dist_version}/arrow-apache-arrow-{dist_version}'
```

### get_build_system_dependencies

The `get_build_system_dependencies()` function should return the PEP
517 build dependencies for a package.

The arguments are the `WorkContext`, the `Requirement` being
evaluated, and the `Path` to the root of the source tree.

The return value is an iterable of requirement specification strings
for build system dependencies for the package. The caller is
responsible for evaluating the requirements with the current build
environment settings to determine if they are actually needed.

```python
# pyarrow.py
def get_build_system_dependencies(ctx, req, sdist_root_dir):
    # The _actual_ directory with our requirements is different than
    # the source root directory detected for the build because the
    # source tree doesn't just include the python package.
    return dependencies.default_get_build_system_dependencies(
        ctx, req,
        sdist_root_dir / 'python',
    )
```

### get_build_backend_dependencies

The `get_build_backend_dependencies()` function should return the PEP
517 build dependencies for a package.

The arguments are the `WorkContext`, the `Requirement` being
evaluated, and the `Path` to the root of the source tree.

The return value is an iterable of requirement specification strings
for build backend dependencies for the package. The caller is
responsible for evaluating the requirements with the current build
environment settings to determine if they are actually needed.

```python
# pyarrow.py
def get_build_backend_dependencies(ctx, req, sdist_root_dir):
    # The _actual_ directory with our requirements is different than
    # the source root directory detected for the build because the
    # source tree doesn't just include the python package.
    return dependencies.default_get_build_backend_dependencies(
        ctx, req,
        sdist_root_dir / 'python',
    )
```

### get_build_sdist_dependencies

The `get_build_sdist_dependencies()` function should return the PEP 517
dependencies for building the source distribution for a package.

The return value is an iterable of requirement specification strings
for build backend dependencies for the package. The caller is
responsible for evaluating the requirements with the current build
environment settings to determine if they are actually needed.

```python
# pyarrow.py
def get_build_sdist_dependencies(ctx, req, sdist_root_dir):
    # The _actual_ directory with our requirements is different than
    # the source root directory detected for the build because the
    # source tree doesn't just include the python package.
    return dependencies.default_get_build_sdist_dependencies(
        ctx, req,
        sdist_root_dir / 'python',
    )
```

### build_sdist

The `build_sdist()` function is responsible for creating a new source
distribution from the prepared source tree and placing it in `ctx.sdists_build`.

The arguments are the `WorkContext`, the `Requirement` being evaluated, and the
`Path` to the root of the source tree.

The return value is the `Path` to the newly created source distribution.

```python
# pyarrow.py
def build_sdist(ctx, req, sdist_root_dir):
    return sources.build_sdist(
        ctx, req,
        sdist_root_dir / 'python',
    )
```

### build_wheel

The `build_wheel()` function is responsible for creating a wheel from
the prepared source tree and placing it in `ctx.wheels_build`.. The
default implementation invokes `pip wheel` in a temporary directory
and passes the path to the source tree as argument.

The arguments are the `WorkContext`, the `Path` to a virtualenv
prepared with the build dependencies, a `dict` with extra environment
variables to pass to the build, the `Requirement` being evaluated, and
the `Path` to the root of the source tree.

The return value is ignored.

```python
def build_wheel(ctx, build_env, extra_environ, req, sdist_root_dir):
    ...
```

## Canonical distribution names

The Python packaging ecosystem is flexible in how the source
distribution, wheel, and python package names are represented in
filenames and requirements specifications. To standardize and ensure
that build customizations are recognized correctly, we always use a
canonical version of the name, computed using
`packaging.utils.canonicalize_name()` and then replacing hyphens (`-`)
with underscores (`_`). For convenience, the `canonicalize`
command will print the correct form of a name.

```console
$ tox -e cli -- canonicalize flit-core
flit_core
```

## Process hooks

Fromager supports plugging in Python hooks to be run after build events.

### post_build

The `post_build` hook runs after a wheel is successfully built and can be used
to publish that wheel to a package index or take other post-build actions.

Configure a `post_build` hook in your `pyproject.toml` like this:

```toml
[project.entry-points."fromager.hooks"]
post_build = "package_plugins.module:function"
```

The input arguments to the `post_build` hook are the `WorkContext`,
`Requirement` being built, the distribution name and version, and the sdist and
wheel filenames.

NOTE: The files should not be renamed or moved.

```python
def post_build(
    ctx: context.WorkContext,
    req: Requirement,
    dist_name: str,
    dist_version: str,
    sdist_filename: pathlib.Path,
    wheel_filename: pathlib.Path,
):
    logger.info(
        f"{req.name}: running post build hook for {sdist_filename} and {wheel_filename}"
    )
```

## Customizations using settings.yaml

To use predefined urls to download sources from, instead of overriding the entire `download_source` function, a mapping of package to download source url can be provided directly in settings.yaml. Optionally the downloaded sdist can be renamed. Both the url and the destination filename support templating. The only supported template variable are:

- `version` - it is replaced by the version returned by the resolver
- `canonicalized_name` - it is replaced by the canonicalized name of the package specified in the requirement, specifically it applies `canonicalize_name(req.nam)`

The source distribution index server used by the package resolver can be overriden for a particular package. The resolver can also be told to whether include wheels or sdist sources while trying to resolve the package. Templating is not supported here.

A `build_dir` field can also be defined to indicate to fromager where the package should be build relative to the sdist root directory

```yaml
packages:
    torch:
        download_source:
            url: "https://github.com/pytorch/pytorch/releases/download/v${version}/pytorch-v${version}.tar.gz"
            destination_filename: "${canonicalized_name}-${version}.tar.gz"
        resolver_dist:
            sdist_server_url: "https://pypi.org/simple"
            include_wheels: true
            include_sdists: false
        build_dir: directory name relative to sdist directory, defaults to an empty string, which means to use the sdist directory
```

### Customizations using package-specific settings files

In addition to the unified settings file, package settings can be saved in their
own file in the directory specified with `--settings-dir`. Files should be named
using the canonicalized form of the package name with the suffix `.yaml`. The
data from the file is treated as though it appears in the
`packages.package_name` section of the main settings file.  Files are read in
lexicographical order. Settings in package-specific files override all settings
in the global file.

```yaml
# settings/torch.yaml
download_source:
    url: "https://github.com/pytorch/pytorch/releases/download/v${version}/pytorch-v${version}.tar.gz"
    destination_filename: "${canonicalized_name}-${version}.tar.gz"
resolver_dist:
    sdist_server_url: "https://pypi.org/simple"
    include_wheels: true
    include_sdists: false
build_dir: directory name relative to sdist directory, defaults to an empty string, which means to use the sdist directory
```

### `pyproject_overrides` section

The `pyproject_overrides` configures the `pyproject.toml` auto-fixer. It can automatically create a missing `pyproject.toml` or modify it.

- `auto_build_requires` is a mapping of Python top-level import name to a requirement (Python distribution name with optional version constraints). The auto-fixer scans `setup.py` for imports and automatically injects `[build-system] requires` for each detected import.
- `remove_build_requires` is a list of distribution names. Any build requirement in the list is removed from `[build-system] requires`.
- `replace_build_requires` is a mapping of Python distribution name to a requirement. Any matching build requirement is replaced by the new requirement.

```yaml
pyproject_overrides:
    enable: true
    auto_build_requires:
        ninja: ninja
        torch: torch<2.4.0,>=2.3.1
    remove_build_requires:
        - cmake
    replace_build_requires:
        distutils: setuptools>=68.0.0
        setuptools: setuptools>=68.0.0
```
