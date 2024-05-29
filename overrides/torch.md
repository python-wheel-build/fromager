# Notes on building torch

## Source

PyTorch does not publish sdists, so we build using a PyTorch release tarball that is not strictly an sdist. Instead we use an archive of the git repo produced by the create_release workflow which (crucially) includes the `third_party/` submodules.

## Patches

### cmake build requirement

The `cmake` Python package is listed as a build requirement in `pyproject.toml`. We favor the RPM-packaged version, so we just remove it from the list of Python build requirements.

### Speeding up python setup.py dist_info

In pyproject.toml, targets like `clean` and `sdist` set the `RUN_BUILD_DEPS=False` flag, which greatly reduces the work done. We use `dist_info` during the build process, and this can be similary sped up.

## Background Information

### Upstream build jobs

It can be helpful to understand how exactly upstream builds wheels.

The easiest entrypoint to these jobs is probably the CI status page - see e.g. [the HUD for the release/2.2 branch](https://hud.pytorch.org/hud/pytorch/pytorch/release%2F2.2). For any given commit, you can find the wheel-building jobs of interest - e.g. `manywheel-py3_11-cpu-build / build`.

If you want the build job for a given release, you should use the commit hash for the release tag.

```
$ git fetch --tags origin
...
$ git rev-parse v2.2.2 v2.2.2-rc3 v2.2.2-rc2 v2.2.2-rc1
39901f229520a5256505ec24782f716ee7ddc843
39901f229520a5256505ec24782f716ee7ddc843
13a5142f56c4c8d6e07ba760df493791b045dd2e
13a5142f56c4c8d6e07ba760df493791b045dd2e
```

Note, release-versioned wheels (like `torch-2.2.2+cpu-cp311-cp311-linux_x86_64.whl`) are triggered when a `-rc` tag is pushed.

The [_binary-build-linux workflow](https://github.com/pytorch/pytorch/blob/main/.github/workflows/_binary-build-linux.yml) calls the [builder/manywheel/build.sh](https://github.com/pytorch/builder/blob/main/manywheel/build.sh) which ultimately calls `python setup.py bdist`.

### Fedora package

Details of the Fedora RPM package can be found [here](https://packages.fedoraproject.org/pkgs/python-torch/python3-torch/). The [python-torch.spec file](https://src.fedoraproject.org/rpms/python-torch/blob/rawhide/f/python-torch.spec) and [logs from builds](https://koji.fedoraproject.org/koji/packageinfo?packageID=39050) are useful sources of information.

### gcc vs clang

The [Fedora Packaging Guidelines state](https://docs.fedoraproject.org/en-US/packaging-guidelines/#compiler):

> Fedora packages should default to using gcc as the compiler (for all languages that gcc supports) or clang if upstream does not support building with gcc.

Upstream builds PyTorch with gcc. In Fedora 40 and before, clang is [used](https://src.fedoraproject.org/rpms/python-torch/c/48192fa108ef9dfb82ed2bc9300f1b692b1b0ede) to build the PyTorch RPM, but this has been [changed](https://src.fedoraproject.org/rpms/python-torch/c/a2a745f76669f491ca2975e1dec7dc8ca7c51458) for later versions.

Check build logs for e.g.

```
-- The CXX compiler identification is GNU 9.3.1
```

or:

```
-- The CXX compiler identification is GNU 14.0.1
```

or:

```
-- The CXX compiler identification is Clang 18.1.1
```

### -Wno-maybe-uninitialized

Upstream [disables](https://github.com/pytorch/pytorch/pull/9608) `-Wmaybe-unitialized` because it is seen as unreliable.

There are [known issues building](https://github.com/pytorch/FBGEMM/issues/1666) FBGEMM with `-Wmaybe-unitialized` and a [gcc 12 regression](https://gcc.gnu.org/bugzilla/show_bug.cgi?id=105593) is referenced.

cmake tests for availability of this flag:

```
Performing Test HAS_WNO_MAYBE_UNINITIALIZED
Performing Test HAS_WNO_MAYBE_UNINITIALIZED - Success
```

However, this does not get passed through to `third_party/fbgemm` so we patch its `CMakeLists.txt`
to add this flag.

For reference, this is the error we were seeing when building with GCC 14.0.1:

```
/usr/bin/c++ [...] -Wall -Wextra -Werror -Wno-deprecated-declarations -Wimplicit-fallthrough -O3 -DNDEBUG -std=c++17 [...] pytorch-v2.2.2/third_party/fbgemm/src/UtilsAvx512.cc
...
pytorch-v2.2.2/third_party/fbgemm/src/UtilsAvx512.cc:970:35: error: ‘r’ may be used uninitialized [-Werror=maybe-uninitialized]
    970 |   d[0] = _mm512_permutex2var_epi32(r[0], index1, r[1]);
```

### FBGEMM

Given the above issue building fbgemm with newer gcc, we considered following the example of the Fedora RPM and disabling fbgemm using `USE_FBGEMM=OFF`. What would the implications of this be?

fbgemm is described as:

> Facebook GEneral Matrix Multiplication) is a low-precision, high-performance matrix-matrix multiplications and convolution library for server-side inference. This library is used as a backend of Caffe2 and PyTorch quantized operators on x86 machines.

i.e. it's a library for quantizated inferencing on x86. See: https://pytorch.org/docs/stable/quantization.html

(Note: torch.ao means “architecture optimization” - “it will include quantization, sparsity and pruning and other ao techniques”)

> Today, PyTorch supports the following backends for running quantized operators efficiently:
>
> * x86 CPUs with AVX2 support or higher (without AVX2 some operations have inefficient implementations), via x86 optimized by fbgemm and onednn (see the details at RFC)

This "unified quantization backend" named "x86" uses fbgemm for some operations and onednn for others, and is only enabled when built with `USE_FBGEMM=ON`.

Without fbgemm enabled, the [PTSQ API Example]([https://pytorch.org/docs/stable/quantization.html#post-training-static-quantization) using the "x86" qconfig will fail with:

```
RuntimeError: Didn't find engine for operation quantized::conv2d_prepack NoQEngine
```

See [aten/src/ATen/native/quantized/cpu/qconv_prepack.cpp](https://github.com/pytorch/pytorch/blob/25f321b84fd3057514d7363b58f592d23e931bd6/aten/src/ATen/native/quantized/cpu/qconv_prepack.cpp#L664-L677) for details.
