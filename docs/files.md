# Input and Output Files

## constraints.txt

The `constraints.txt` is the input file used to control the resolution of python packages that are needed to build a wheel. This file is similar to `requirements.txt` but instead of listing packages that must be installed, it sets constraints on versions of packages, ensuring that certain versions are either used or avoided during the wheel building process.

Each line in the `constraints.txt` file should contain the name of a package followed by a version specifier. The syntax for version specifier can be found [here](https://pip.pypa.io/en/stable/reference/requirements-file-format/)

### Example constraints.txt

```
torch==2.3.1
pandas<2.2.2
setuptools!=72.0.0
```

## build-order.json

The `build-order.json` file is an output file that contains the bottom-up order in which the dependencies need to be built for a specific wheel.

This file contains an array of objects where each object represents a dependency and necessary information related to it. The order of these objects determines the build sequence, starting with the top-level dependency at the bottom of the array.

### Example build-order.json

The following example shows `build-order.json` file for the top-level dependency `wheel`

```json
[
  {
    "type": "build-system",
    "req": "flit_core<4,>=3.8",
    "constraint": "",
    "dist": "flit-core",
    "version": "3.9.0",
    "prebuilt": false,
    "source_url": "https://files.pythonhosted.org/packages/c4/e6/c1ac50fe3eebb38a155155711e6e864e254ce4b6e17fe2429b4c4d5b9e80/flit_core-3.9.0.tar.gz#sha256=72ad266176c4a3fcfab5f2930d76896059851240570ce9a98733b658cb786eba",
    "source_url_type": "sdist"
  },
  {
    "type": "toplevel",
    "req": "wheel",
    "constraint": "",
    "dist": "wheel",
    "version": "0.44.0",
    "prebuilt": false,
    "source_url": "https://files.pythonhosted.org/packages/b7/a0/95e9e962c5fd9da11c1e28aa4c0d8210ab277b1ada951d2aee336b505813/wheel-0.44.0.tar.gz#sha256=a29c3f2817e95ab89aa4660681ad547c0e9547f20e75b0562fe7723c9a2a9d49",
    "source_url_type": "sdist"
  }
]
```

## graph.json

The `graph.json` is an output file that contains all the paths fromager can take to resolve a dependency during building the wheel. The graph represents all of the dependencies encountered during a build of a wheel collection ("collection" is a new term we're introducing). It shows the parent/child relationships of all dependencies, including the type of dependency.

The format is a mapping from resolved versions expressed as a requirement specification (package==version) to a mapping with properties of the package and the list of dependencies of that package.

### Example graph.json

The following example shows `graph.json` file for the top-level dependency `wheel`

```json
{
  "": {
    "download_url": "",
    "version": "0",
    "canonicalized_name": "",
    "edges": [
      {
        "key": "wheel==0.44.0",
        "req_type": "toplevel",
        "req": "wheel"
      }
    ]
  },
  "wheel==0.44.0": {
    "download_url": "",
    "version": "0.44.0",
    "canonicalized_name": "wheel",
    "edges": [
      {
        "key": "flit-core==3.9.0",
        "req_type": "build-system",
        "req": "flit_core<4,>=3.8"
      }
    ]
  },
  "flit-core==3.9.0": {
    "download_url": "",
    "version": "3.9.0",
    "canonicalized_name": "flit-core",
    "edges": []
  }
}
```

## Output Directories

During the wheel building process, fromager generates multiple output directories namely `sdists-repo`, `wheels-repo` and `work-dir`. These directories contain important information related to the wheel build.

### sdist-repo

This directory contains the source distributions for the package and its dependencies that we are building. The directory structure of `sdists-repo` is as follows

```
sdists-repo
├── builds
└── downloads
```

The `builds` and `downloads` sub-directories contain the source distributions that are built and downloaded respectively. The `downloads` directory includes the original sdist from upstream and the `builds` directory contains the sdist created by fromager after any patches are applied. For example, the `sdists-repo` for `stevedore` package looks as follows:

```
sdists-repo
├── builds
│   ├── pbr-6.1.0.tar.gz
│   ├── setuptools-75.1.0.tar.gz
│   └── stevedore-5.3.0.tar.gz
└── downloads
    ├── pbr-6.1.0.tar.gz
    ├── setuptools-75.1.0.tar.gz
    └── stevedore-5.3.0.tar.gz

```

We can see source distributions for `pbr` and `setuptools` since these are dependencies of `stevedore`.

### wheels-repo

This directory contains the wheels for a package and its dependencies that are built by fromager, used as prebuilt and the ones that are downloaded from indices. The directory structure of `wheels-repo` is as follows

```
wheels-repo
├── build
├── downloads
├── prebuilt
└── simple
```

* The `build` sub-directoy holds temporary builds. We use it as the output directory when building the wheel because we can't predict the filename, and so using an empty directory with a name we know gives us a way to find the file and move it into the `downloads` directory after it's built
* The `downloads` sub-directory contains the wheels in `.whl` format that fromager builds combined with the pre-built wheels so we can create a local package index in `simple`
* The `prebuilt` sub-directory contains wheels that are being used as prebuilt
* The `simple` sub-directory is managed by [pypi-mirror](https://pypi.org/project/pypi-mirror/) to create a local wheel index.

For example, the `wheels-repo` for `stevedore` package looks as follows:

```
wheels-repo
├── build
├── downloads
│   ├── pbr-6.1.0-0-py2.py3-none-any.whl
│   ├── setuptools-75.1.0-0-py3-none-any.whl
│   └── stevedore-5.3.0-0-py3-none-any.whl
├── prebuilt
└── simple
    ├── index.html
    ├── pbr
    │   ├── index.html
    │   └── pbr-6.1.0-0-py2.py3-none-any.whl
    ├── setuptools
    │   ├── index.html
    │   └── setuptools-75.1.0-0-py3-none-any.whl
    └── stevedore
        ├── index.html
        └── stevedore-5.3.0-0-py3-none-any.whl

```

### work-dir

This directory contains information that is required during the wheel build process. This information includes logs, constraints, requirements, graph for dependency resolution and the order in which the package and its dependencies will be built. The directory structure of `work-dir` is as follows:

```
work-dir
├── build-order.json
├── constraints.txt
├── graph.json
├── logs
├── sample-package-foo
   ├── simple-package-foo
   ├── build-backend-requirements.txt
   ├── build.log
   ├── build-meta.json
   ├── build-sdist-requirements.txt
   ├── build-system-requirements.txt
   └── requirements.txt

```

* The `build-order.json` file is an output file that contains the bottom-up order in which the dependencies need to be built for a specific wheel. You can find more details [here](https://fromager.readthedocs.io/en/latest/files.html#build-order-json)
* The `constraints.txt` is the output file, produced by fromager, showing all of the versions of the packages that are install-time dependencies of the top-level items
* The `graph.json` is an output file that contains all the paths fromager can take to resolve a dependency during building the wheel. You can find more details [here](https://fromager.readthedocs.io/en/latest/files.html#graph-json)
* The `logs` sub-directory contains detailed logs for fromager's `build-sequence` command including various settings and overrides for each individual package and its dependencies whose wheel was built by fromager. Each log file also contains information about build-backend dependencies if present for a given package
* The `work-dir` also includes sub-directories for the package and its dependencies. These sub-directories include various types of requirements files including `build-backend-requirements.txt`, `build-sdists-requirements.txt`, `build-system-requirements.txt` and the general `requirements.txt`. Files like `build.log` which store the logs generated by pip and `build-meta.json` that stores the metadata for the build are also located in `work-dir`. These sub-directories also include all the other relevant information for a particular package. Each sub-directory of the package will also contain the unpacked source code of each wheel that is used for the build if `--no-cleanup` option of fromager is used. For example, in the above directory structure, for `simple-package-foo` requirement, we will have a subdirectory titled `simple-package-foo` that holds the unpacked source code

For example, the `work-dir` for `stevedore` package after `bootstrap` command looks as follows:

```
work-dir
├── build-order.json
├── constraints.txt
├── graph.json
├── logs
├── pbr-6.1.0
│   ├── build-backend-requirements.txt
│   ├── build.log
│   ├── build-meta.json
│   ├── build-sdist-requirements.txt
│   ├── build-system-requirements.txt
│   └── requirements.txt
├── setuptools-75.1.0
│   ├── build-backend-requirements.txt
│   ├── build.log
│   ├── build-meta.json
│   ├── build-sdist-requirements.txt
│   ├── build-system-requirements.txt
│   └── requirements.txt
└── stevedore-5.3.0
    ├── build-backend-requirements.txt
    ├── build.log
    ├── build-meta.json
    ├── build-sdist-requirements.txt
    ├── build-system-requirements.txt
    └── requirements.txt
```
