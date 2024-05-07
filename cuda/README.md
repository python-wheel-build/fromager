# Building with CUDA support

The tools in this directory can be used to build wheels on UBI9 images
with CUDA 12.3.2 support.

The `build_cuda.sh` script takes as input a build-order.json file, as
is created by following the bootstrapping process.

```
$ tox -e job -- bootstrap -o llama-cpp-build-order.json llama-cpp-python 0.2.55
...
```

After creating the build order file and onboarding, run
`build_cuda.sh`.

```
$ ./cuda/build_cuda.sh ./llama-cpp-build-order.json
...
```

The built wheels are saved in `wheels-repo/downloads` and can be
uploaded to an index from there.

```
$ ls wheels-repo/downloads
calver-2022.6.26-py3-none-any.whl
Cython-3.0.10-cp311-cp311-linux_x86_64.whl
diskcache-5.6.3-py3-none-any.whl
distro-1.9.0-py3-none-any.whl
flit_core-3.9.0-py3-none-any.whl
hatch_fancy_pypi_readme-24.1.0-py3-none-any.whl
hatchling-1.24.2-py3-none-any.whl
hatch_vcs-0.4.0-py3-none-any.whl
jinja2-3.1.4-py3-none-any.whl
llama_cpp_python-0.2.55-cp311-cp311-linux_x86_64.whl
MarkupSafe-2.1.5-cp311-cp311-linux_x86_64.whl
meson-1.4.0-py3-none-any.whl
meson_python-0.15.0-py3-none-any.whl
packaging-24.0-py3-none-any.whl
patchelf-0.18.0.0-py2.py3-none-linux_x86_64.whl
pathspec-0.12.1-py3-none-any.whl
pluggy-1.5.0-py3-none-any.whl
pyproject_metadata-0.8.0-py3-none-any.whl
scikit_build-0.17.6-py3-none-any.whl
scikit_build_core-0.9.3-py3-none-any.whl
setuptools-69.5.1-py3-none-any.whl
setuptools_scm-8.1.0-py3-none-any.whl
trove_classifiers-2024.4.10-py3-none-any.whl
typing_extensions-4.11.0-py3-none-any.whl
wheel-0.43.0-py3-none-any.whl
```
