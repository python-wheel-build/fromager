# Rebuilding the Wheel

This repo is a prototype of completely re-building a dependency tree of Python wheels from source.

The idea is to explore what is involved with providing a Python package index from which a user can pip install knowing:

1. The [binary package](https://packaging.python.org/en/latest/glossary/#term-Built-Distribution) they are installing was built from source in a known build environment compatible with their own environment
1. All of the package’s dependencies were also built from source - any binary package installed will have been built from source
1. All of the build tools used to build these binary packages will also have been built from source

For the purposes of this prototype, [langchain](https://pypi.org/project/langchain/) was chosen as the top of the dependency stack.

The [mirror-sdists](mirror-sdists.sh) script does the following:

* Creates an empty package repository for [wheels](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)
* Downloads all [source distributions](https://packaging.python.org/en/latest/glossary/#term-Source-Distribution-or-sdist) under `sdists-repo/downloads/` using `pip download` and generates a [PEP503 “simple” package repository](https://peps.python.org/pep-0503/) using [pypi-mirror](https://pypi.org/project/python-pypi-mirror/)
* Three types of dependencies are also downloaded:
  * Firstly, any build system dependency specified in the pyproject.toml build-system.requires section as per [PEP517](https://peps.python.org/pep-0517)
  * Secondly, any build backend dependency returned from the get_requires_for_build_wheel() build backend hook (PEP517 again)
  * Lastly, any install-time dependencies of the project as per the wheel’s [core metadata](https://packaging.python.org/en/latest/specifications/core-metadata/) `Requires-Dist` list.
* These dependencies are downloaded recursively and we record the order they will need to be built bottom-up in a build-order.json file.
* Uses `pip wheel` to build a binary package, only downloading dependencies from the fresh wheel repository
* Places the newly built wheel in the package repository and regenerates the repository listing

Finally, the [install-from-mirror](install-from-mirror.sh) script installs the dependency stack into a virtual environment from this newly created repository of wheels.

### Current Status

See the [currently open issues](https://gitlab.com/fedora/sigs/ai-ml/rebuilding-the-wheel/-/issues)

### Langchain Dependency Tree

For reference, here's the dependency tree we're dealing with in this prototype:

```
$ deptree langchain
langchain==0.1.11
├── aiohttp [required: >=3.8.3,<4.0.0, installed: 3.9.3]
│   ├── aiosignal [required: >=1.1.2, installed: 1.3.1]
│   │   └── frozenlist [required: >=1.1.0, installed: 1.4.1]
│   ├── async-timeout [required: >=4.0,<5.0, installed: 4.0.3]
│   ├── attrs [required: >=17.3.0, installed: 23.2.0]
│   ├── frozenlist [required: >=1.1.1, installed: 1.4.1]
│   ├── multidict [required: >=4.5,<7.0, installed: 6.0.5]
│   └── yarl [required: >=1.0,<2.0, installed: 1.9.4]
│       ├── idna [required: >=2.0, installed: 3.6]
│       └── multidict [required: >=4.0, installed: 6.0.5]
├── async-timeout [required: >=4.0.0,<5.0.0, installed: 4.0.3]
├── dataclasses-json [required: >=0.5.7,<0.7, installed: 0.6.4]
│   ├── marshmallow [required: >=3.18.0,<4.0.0, installed: 3.21.1]
│   │   └── packaging [required: >=17.0, installed: 23.2]
│   └── typing-inspect [required: >=0.4.0,<1, installed: 0.9.0]
│       ├── mypy-extensions [required: >=0.3.0, installed: 1.0.0]
│       └── typing_extensions [required: >=3.7.4, installed: 4.10.0]
├── jsonpatch [required: >=1.33,<2.0, installed: 1.33]
│   └── jsonpointer [required: >=1.9, installed: 2.4]
├── langchain-community [required: >=0.0.25,<0.1, installed: 0.0.27]
│   ...
├── langchain-core [required: >=0.1.29,<0.2, installed: 0.1.30]
│   ├── anyio [required: >=3,<5, installed: 4.3.0]
│   │   ├── exceptiongroup [required: >=1.0.2, installed: 1.2.0]
│   │   ├── idna [required: >=2.8, installed: 3.6]
│   │   ├── sniffio [required: >=1.1, installed: 1.3.1]
│   │   └── typing_extensions [required: >=4.1, installed: 4.10.0]
│   ...
│   ├── packaging [required: >=23.2,<24.0, installed: 23.2]
│   ...
├── langchain-text-splitters [required: >=0.0.1,<0.1, installed: 0.0.1]
│   └── langchain-core [required: >=0.1.28,<0.2.0, installed: 0.1.30]
│       ...
├── langsmith [required: >=0.1.17,<0.2.0, installed: 0.1.23]
│   ├── orjson [required: >=3.9.14,<4.0.0, installed: 3.9.15]
│   ...
├── numpy [required: >=1,<2, installed: 1.26.4]
├── pydantic [required: >=1,<3, installed: 2.6.3]
│   ├── annotated-types [required: >=0.4.0, installed: 0.6.0]
│   ├── pydantic_core [required: ==2.16.3, installed: 2.16.3]
│   │   └── typing_extensions [required: >=4.6.0,!=4.7.0, installed: 4.10.0]
│   └── typing_extensions [required: >=4.6.1, installed: 4.10.0]
├── PyYAML [required: >=5.3, installed: 6.0.1]
├── requests [required: >=2,<3, installed: 2.31.0]
│   ├── certifi [required: >=2017.4.17, installed: 2024.2.2]
│   ├── charset-normalizer [required: >=2,<4, installed: 3.3.2]
│   ├── idna [required: >=2.5,<4, installed: 3.6]
│   └── urllib3 [required: >=1.21.1,<3, installed: 2.2.1]
├── SQLAlchemy [required: >=1.4,<3, installed: 2.0.28]
│   ├── greenlet [required: !=0.4.17, installed: 3.0.3]
│   └── typing_extensions [required: >=4.6.0, installed: 4.10.0]
└── tenacity [required: >=8.1.0,<9.0.0, installed: 8.2.3]
```

### Running Pipelines

The project uses gitlab pipelines for building. As a convenience,
there is a command line program available for users who have access to
a GitLab token with permission to trigger pipelines in the
`GITLAB_TOKEN` environment variable.

To run the bootstrap job for `setuptools` version `69.5.1`, use:

```
$ tox -e job -- bootstrap -d setuptools -v 69.5.1
```
