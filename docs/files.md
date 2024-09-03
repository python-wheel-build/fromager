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
