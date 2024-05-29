# Rebuilding the Wheel

This repo is a prototype of completely re-building a dependency tree
of Python wheels from source.

The idea is to explore what is involved with providing a Python
package index from which a user can pip install knowing:

1. The [binary
   package](https://packaging.python.org/en/latest/glossary/#term-Built-Distribution)
   they are installing was built from source in a known build
   environment compatible with their own environment
1. All of the package’s dependencies were also built from source - any
   binary package installed will have been built from source
1. All of the build tools used to build these binary packages will
   also have been built from source

The [mirror-sdists](mirror-sdists.sh) script does the following:

* Creates an empty package repository for
  [wheels](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)
* Downloads all [source
  distributions](https://packaging.python.org/en/latest/glossary/#term-Source-Distribution-or-sdist)
  under `sdists-repo/downloads/` using `pip download` and generates a
  [PEP503 “simple” package
  repository](https://peps.python.org/pep-0503/) using
  [pypi-mirror](https://pypi.org/project/python-pypi-mirror/)
* Three types of dependencies are also downloaded:
  * Firstly, any build system dependency specified in the
    pyproject.toml build-system.requires section as per
    [PEP517](https://peps.python.org/pep-0517)
  * Secondly, any build backend dependency returned from the
    get_requires_for_build_wheel() build backend hook (PEP517 again)
  * Lastly, any install-time dependencies of the project as per the
    wheel’s [core
    metadata](https://packaging.python.org/en/latest/specifications/core-metadata/)
    `Requires-Dist` list.
* These dependencies are downloaded recursively and we record the
  order they will need to be built bottom-up in a build-order.json
  file.
* Uses `pip wheel` to build a binary package, only downloading
  dependencies from the fresh wheel repository
* Places the newly built wheel in the package repository and
  regenerates the repository listing

Finally, the [install-from-mirror](install-from-mirror.sh) script
installs the dependency stack into a virtual environment from this
newly created repository of wheels.

## Additional docs

* [How Tos](docs/howtos.md)
* Some packages have [customizations applied](docs/pkgs/)
* [Developer Instructions](docs/develop.md)

## Using the indexes

The https://pyai.fedorainfracloud.org/experimental/cpu index includes
builds without GPU-specific optimizations. Use the
https://pyai.fedorainfracloud.org/experimental/cpu/+simple/ index with
pip to install packages from the index.

```
$ python3 -m venv numpy-test
$ source numpy-test/bin/activate
$ pip install --index-url https://pyai.fedorainfracloud.org/experimental/cpu/+simple/ numpy
```
