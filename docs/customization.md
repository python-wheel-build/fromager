# Customizing parts of the package build process

Fromager support customizing most aspects of the build process,
including acquiring the source, applying local patches, passing
arguments to the build, and providing a custom build command.

## Package name

(canonical-distribution-names)=

Fromager normalizes a package name into one of two forms. Settings files,
patch directories, and override plugins use the *override name*. All other
places use the normalized, *canonical name*.

```python
import re

def canonicalize_name(name: str) -> NormalizedName:
    return re.sub(r"[-_.]+", "-", name).lower()

def override_name(name: str | NormalizedName) -> str:
    return canonicalize_name(name).replace("-", "_")
```

See PyPA spec for package
[names and normalization](https://packaging.python.org/en/latest/specifications/name-normalization/)
for more information.

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

## Customizations using using package-specific settings files (`$name.yaml`)

Package settings are read from their own file in the directory specified with
`--settings-dir`. Files should be named using the canonicalized form of the
package name with the suffix `.yaml`, e.g. `torch.yaml` or
`llama_cpp_python.yaml`. Files are read in lexicographical order.

### Example config

```shell
fromager --settings-dir=overrides/settings ...
```

```yaml
# overrides/settings/torch.yaml
download_source:
    url: "https://github.com/pytorch/pytorch/releases/download/v${version}/pytorch-v${version}.tar.gz"
    destination_filename: "${canonicalized_name}-${version}.tar.gz"
resolver_dist:
    sdist_server_url: "https://pypi.org/simple"
    include_wheels: true
    include_sdists: false
build_dir: directory name relative to sdist directory, defaults to an empty string, which means to use the sdist directory
env:
    USE_FFMPEG: "0"
    USE_LEVELDB: "0"
    USE_LMDB: "1"
variants:
    cpu:
        env:
            OPENBLAS_NUM_THREADS: "1"
    gaudi:
        # use pre-built binary wheels from a custom index for this variant
        pre_built: true
        wheel_server_url: https://internal.pypi.example/simple
```

### Download source

To use predefined urls to download sources from, instead of overriding
the entire `download_source` function, a mapping of package to download
source url can be provided directly in settings.yaml. Optionally the
downloaded sdist can be renamed. Both the url and the destination filename
support templating. The only supported template variable are:

- `version` - it is replaced by the version returned by the `resolve_source`
- `canonicalized_name` - it is replaced by the canonicalized name of the
  package specified in the requirement, specifically it applies `canonicalize_name(req.nam)`

### Resolver dist

The source distribution index server used by the package resolver can
be overriden for a particular package. The resolver can also be told
to whether include wheels or sdist sources while trying to resolve
the package. Templating is not supported here.

### Build directory

A `build_dir` field can also be defined to indicate to fromager where the
package should be build relative to the sdist root directory.

### Variant pre-built flag

If the `pre_built` field is set for a variant, then fromager pulls and resolves binary
wheels specified in the field from local wheels server spun up by fromager
followed by upstream package servers instead of rebuilding the package from source.
If an alternate package index is provided in the settings then that is the only
index used.

When downloading a prebuilt wheel by hand, make sure that the wheel is
placed in the `<path to wheels-repo directory>/prebuilt` directory so that it is
picked up by fromager and it doesn't try to download it again. Note that this won't
result in fromager resolving the package using this downloaded wheel. If you want to
make fromager consider this downloaded wheel during resolution as well then place the
prebuilt wheel in the `<path to wheels-repo directory>/downloads` directory. This will
ensure that the local index spun up by fromager picks up the downloaded wheel.

### Build environment variables

Most python packages with configurable builds use environment variables to pass
build parameters. The environment variables set when `fromager` runs are passed
to the build process for each wheel. Sometimes this does not provide sufficient
opportunity for customization, so `fromager` also supports setting build
variables for each package.

The most common reason for passing different environment variables is to support
different build variants, such as to enable different hardware accelerators.
The env vars are defined in the `env` mapping of a variant. Values must be
strings. Values like `1` must be quoted as `"1"`.

Settings common to all variants of a given package can be placed in the the
top-level `env` mapping. Variant env vars override global env vars.

Environment files support simple parameter expansions `$NAME` and
`${NAME}`. Values are taken from previous lines, then global env map, and
finally process environment. Sub shell expression `$(cmd)` and extended
parameter expansions like `${NAME:-default}` are not implemented. A literal
`$` must be quoted as `$$`.

```yaml
# example
env:
    # pre-pend '/global/bin' to PATH
    PATH: "/global/bin:$PATH"
variants:
    cpu:
        env:
            # The cpu variant has 'PATH=/cpu/bin:/global/bin:$PATH`
            PATH: "/cpu/bin:$PATH"
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

## `project_override` section

The `project_override` configures the `pyproject.toml` auto-fixer. It can
automatically create a missing `pyproject.toml` or modify an existing file.
Packages are matched by canonical name.

- `remove_build_requires` is a list of package names. Any build requirement
  in the list is removed
- `update_build_requires` a list of requirement specifiers. Existing specs
  are replaced and missing specs are added. The option can be used to add,
  remove, or change a version constraint.

```yaml
project_override:
    remove_build_requires:
        - cmake
    update_build_requires:
        - setuptools>=68.0.0
        - torch
        - triton
```

Incoming `pyproject.toml`:

```yaml
[build-system]
requires = ["cmake", "setuptools>48.0", "torch>=2.3.0"]
```

Output:

```yaml
[build-system]
requires = ["setuptools>=68.0.0", "torch", "triton"]
```

## Override plugins

Override plugins are documented in [the reference guide](hooks.rst).

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
