# Using these tools

## Setup

The project uses gitlab pipelines for building. As a convenience,
there is a command line program available for users who have access to
a GitLab token with permission to trigger pipelines in the
`GITLAB_TOKEN` environment variable.

## Running Pipelines

To run the bootstrap job for `setuptools` version `69.5.1`, use:

```
$ tox -e job -- bootstrap setuptools 69.5.1
```

To run the job to build the wheel for the same package:

```
$ tox -e job -- build-wheel setuptools 69.5.1
```

To get help, use

```
$ tox -e job -- -h
```

## Adding a new package to the index

The system is designed to only build source it knows about, and to
reuse previously built content while building new packages. To add
something new to the set of buildable packages, the source package
(sdist) for the new package and all of its build or runtime
dependencies must be uploaded, then built in the proper order.

### Bootstrapping

The first step in adding a new package is to "bootstrap" it to produce
a "build order file". Bootstrapping happens without the same
restrictions as regular builds, so that new dependencies or new
versions of dependencies can be downloaded from upstream locations
such as https://pypi.org.

The output of bootstrapping is a JSON file listing all of the things
that need to be built, in the order they need to be built, before
building the package being added. For example, even though NumPy
itself does not have installation-time dependencies, the bootstrap
output for `NumPy` version `1.26.4` includes many build dependencies
and _their_ installation-time dependencies.

```
[
  {
    "type": "build_system",
    "req": "flit-core",
    "dist": "flit-core",
    "version": "3.9.0",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> pyproject-metadata(0.8.0)"
  },
  {
    "type": "build_system",
    "req": "pyproject-metadata>=0.7.1",
    "dist": "pyproject-metadata",
    "version": "0.8.0",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0)"
  },
  {
    "type": "dependency",
    "req": "packaging>=19.0",
    "dist": "packaging",
    "version": "24.0",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> pyproject-metadata(0.8.0)"
  },
  {
    "type": "build_backend",
    "req": "wheel",
    "dist": "wheel",
    "version": "0.43.0",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> meson(1.4.0) -> setuptools(69.5.1)"
  },
  {
    "type": "build_system",
    "req": "setuptools>=42",
    "dist": "setuptools",
    "version": "69.5.1",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> meson(1.4.0)"
  },
  {
    "type": "build_system",
    "req": "meson>=0.63.3; python_version < \"3.12\"",
    "dist": "meson",
    "version": "1.4.0",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0)"
  },
  {
    "type": "build_backend",
    "req": "pathspec>=0.10.1",
    "dist": "pathspec",
    "version": "0.12.1",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> patchelf(0.18.0.0) -> scikit-build(0.17.6) -> hatch-vcs(0.4.0) -> hatchling(1.24.2)"
  },
  {
    "type": "build_system",
    "req": "setuptools-scm[toml]>=6.2.3",
    "dist": "setuptools-scm",
    "version": "8.0.4",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> patchelf(0.18.0.0) -> scikit-build(0.17.6) -> hatch-vcs(0.4.0) -> hatchling(1.24.2) -> pluggy(1.5.0)"
  },
  {
    "type": "dependency",
    "req": "typing-extensions",
    "dist": "typing-extensions",
    "version": "4.11.0",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> patchelf(0.18.0.0) -> scikit-build(0.17.6) -> hatch-vcs(0.4.0) -> hatchling(1.24.2) -> pluggy(1.5.0) -> setuptools-scm(8.0.4)"
  },
  {
    "type": "build_backend",
    "req": "pluggy>=1.0.0",
    "dist": "pluggy",
    "version": "1.5.0",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> patchelf(0.18.0.0) -> scikit-build(0.17.6) -> hatch-vcs(0.4.0) -> hatchling(1.24.2)"
  },
  {
    "type": "build_system",
    "req": "calver",
    "dist": "calver",
    "version": "2022.6.26",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> patchelf(0.18.0.0) -> scikit-build(0.17.6) -> hatch-vcs(0.4.0) -> hatchling(1.24.2) -> trove-classifiers(2024.4.10)"
  },
  {
    "type": "build_backend",
    "req": "trove-classifiers",
    "dist": "trove-classifiers",
    "version": "2024.4.10",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> patchelf(0.18.0.0) -> scikit-build(0.17.6) -> hatch-vcs(0.4.0) -> hatchling(1.24.2)"
  },
  {
    "type": "build_system",
    "req": "hatchling>=1.1.0",
    "dist": "hatchling",
    "version": "1.24.2",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> patchelf(0.18.0.0) -> scikit-build(0.17.6) -> hatch-vcs(0.4.0)"
  },
  {
    "type": "build_system",
    "req": "hatch-vcs",
    "dist": "hatch-vcs",
    "version": "0.4.0",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> patchelf(0.18.0.0) -> scikit-build(0.17.6)"
  },
  {
    "type": "build_system",
    "req": "hatch-fancy-pypi-readme",
    "dist": "hatch-fancy-pypi-readme",
    "version": "24.1.0",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> patchelf(0.18.0.0) -> scikit-build(0.17.6)"
  },
  {
    "type": "build_system",
    "req": "scikit-build>=0.12",
    "dist": "scikit-build",
    "version": "0.17.6",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> patchelf(0.18.0.0)"
  },
  {
    "type": "dependency",
    "req": "distro",
    "dist": "distro",
    "version": "1.9.0",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0) -> patchelf(0.18.0.0) -> scikit-build(0.17.6)"
  },
  {
    "type": "build_backend",
    "req": "patchelf>=0.11.0",
    "dist": "patchelf",
    "version": "0.18.0.0",
    "why": " -> numpy(1.26.4) -> meson-python(0.15.0)"
  },
  {
    "type": "build_system",
    "req": "meson-python<0.16.0,>=0.15.0",
    "dist": "meson-python",
    "version": "0.15.0",
    "why": " -> numpy(1.26.4)"
  },
  {
    "type": "build_system",
    "req": "Cython<3.1,>=0.29.34",
    "dist": "cython",
    "version": "3.0.10",
    "why": " -> numpy(1.26.4)"
  },
  {
    "type": "toplevel",
    "req": "numpy",
    "dist": "numpy",
    "version": "1.26.4",
    "why": ""
  }
]
```

To run the bootstrap job for `NumPy` version `1.26.4` in a GitLab
pipeline, use:

```
$ tox -e job -- bootstrap --show-progress --output numpy-build-order.json NumPy 1.26.4
```

The build order content will be written to the file passed as argument
to `--output`.

For packages that do not yet build in CI (such as Torch, which
requires more CPU capacity than is available to the build host to
compile in a reasonable amount of time), you can bootstrap locally
using `mirror-sdists.sh`.

```
$ ./mirror-sdists.sh NumPy==1.26.4
```

The output is written to `work-dir/build-order.json`.

**NOTE:** The dependencies of a package may vary based on the version
of Python used to calculate those dependencies. For example, as new
features are added to the standard library, some external libraries
are no longer needed. Requirement "environment markers", as described
in [PEP-508](https://peps.python.org/pep-0508/), can be used to
express these sorts of dynamic dependencies. If you are building
something for multiple versions of Python, it should be bootstrapped
for each of those versions separately to ensure accurate dependencies
are calculated, and then those separate output files should be passed
to each of the following steps, along with the corresponding Python
version. Use the `--python` flag when running the job, or set `PYTHON`
to a Python interpreter command name when running locally.

### Onboarding source files

After the build order file is produced, the next step is to use that
file to upload the source archives (also known as "source dists" or
"sdists") to the source hosting repository on the index server. This
step should be performed via a job since it requires access to the
tokens for the index server.

```
$ tox -e job -- onboard-sequence ./work-dir/build-order.json
```

### Building wheels

With the source files in place, the next step is to build the wheel
packages. The build process may produce different output based on the
Python version, CPU type, etc. The build pipeline should take care of
those differences.

```
$ tox -e job -- build-sequence ./work-dir/build-order.json
```

Be certain to use `--python` to pass the Python interpreter name to
use with the list of packages in the build order file.

## Updating tools

When these tools run in the build pipelines, their dependencies are
only installed from the
[internal/tools](https://pyai.fedorainfracloud.org/internal/tools)
repository. Adding new tools, or updating versions of existing tools,
is a manual process and requires a token for the package server's
"internal" user.

First, clean up to ensure only tools will be uploaded:

```
$ rm -rf work-dir/ wheels-repo/ sdists-repo/
```

Then bootstrap the dependencies locally. This process does not rely on
the build order file, so it is possible to bootstrap multiple
dependencies at the same time by running the command more than
once. All of the sdists and wheels will be written to the common
output directory, from which they can be uploaded to the index.

```
$ ./mirror-sdists.sh devpi
$ ./mirror-sdists.sh twine
```

Finally, use `twine` or `devpi` to upload those dependencies to the
`internal/tools` repository. Include the sdist and wheel files.

```
$ devpi login internal
password for user internal at https://pyai.fedorainfracloud.org/:
logged in 'internal' at 'https://pyai.fedorainfracloud.org/internal/tools', credentials valid for 10.00 hours
$ devpi use internal/tools
current devpi index: https://pyai.fedorainfracloud.org/internal/tools (logged in as internal)
...
$ devpi upload wheels-repo/downloads/*.whl sdists-repo/downloads/*.tar.gz
```
