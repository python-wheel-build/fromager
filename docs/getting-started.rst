Getting Started
===============

The basic process for using fromager to build a collection of wheels is

1. Make a list of the top-level dependencies (applications, extension libraries,
   etc.) in a `requirements.txt` file.
2. Make a list of known constraints for common dependencies. For example, if you
   are building 2 applications that both depend on the same library but express
   that dependency in different ways, you can select the version of that library
   that you want so only one version is built. Save this list in a
   `constraints.txt` file.
3. Run `bootstrap`, passing your `requirements.txt` and `constraints.txt`, to
   try to build the collection.
4. When a package fails to build, create a settings file and mark it as
   pre-built. This lets you move through the full set of dependencies quickly,
   and build a list of the problematic packages.
5. When the build completes, review the set of pre-built packages and
   iteratively "fix" each one so that you are able to build it. Typical reasons
   for failure include missing system dependencies, packages that have no source
   distributions, and packages for which wheels cannot be built from the source
   distribution because it is incomplete.

It may be useful to use a container to run fromager so you can use the
`Containerfile` to manage the build-time dependencies.

Example Bootstrap Session
-------------------------

We will use `pydantic-core` and a `Universal Base Image (UBI) for Red Hat
Enterprise Linux 9 <https://catalog.redhat.com/software/base-images>`__ to
demonstrate debugging and fixing a build failure.

Inputs
~~~~~~

We can start with a ``requirements.txt`` file:

.. literalinclude:: example/requirements.txt
   :caption: requirements.txt

and an empty `constraints.txt`.

The build container includes Python, rust, and a virtualenv with fromager
installed:

.. literalinclude:: example/Containerfile
   :caption: Containerfile

First try
~~~~~~~~~

Then we can use the ``bootstrap.sh`` script in the ``docs/example`` directory to
build and test the image:

.. literalinclude:: example/bootstrap.sh
   :caption: bootstrap.sh

The output below is redacted for brevity. Missing sections are replaced with ``...``.

.. code-block:: console
   :emphasize-lines: 61

   $ cd docs/example
   $ ./bootstrap.sh ./constraints.txt ./requirements.txt

   ...

   podman run -it --rm --security-opt label=disable --volume ./bootstrap-output:/work/bootstrap-output:rw,exec --volume ./bootstrap-ccache:/var/cache/ccache:rw,exec --volume ././constraints.txt:/bootstrap-inputs/constraints.txt --volume ././requirements.txt:/bootstrap-inputs/requirements.txt wheels-builder fromager --constraints-file /bootstrap-inputs/constraints.txt --log-file=bootstrap-output/bootstrap.log --sdists-repo=bootstrap-output/sdists-repo --wheels-repo=bootstrap-output/wheels-repo --work-dir=bootstrap-output/work-dir bootstrap -r /bootstrap-inputs/requirements.txt
   logging debug information to bootstrap-output/bootstrap.log
   primary settings file: overrides/settings.yaml
   per-package settings dir: overrides/settings
   variant: cpu-fedora
   patches dir: overrides/patches
   maximum concurrent jobs: None
   constraints file: /bootstrap-inputs/constraints.txt
   wheel server url:
   network isolation: True
   loading constraints from /bootstrap-inputs/constraints.txt
   bootstrapping 'cpu-fedora' variant of [<Requirement('pydantic-core==2.18.4')>]
   no previous bootstrap data
   resolving top-level dependencies before building
   pydantic-core==2.18.4 resolves to 2.18.4

   ...

   pydantic-core: building wheel for pydantic-core==2.18.4 in /work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4 writing to /work/bootstrap-output/wheels-repo/build
   ['/usr/bin/unshare', '--net', '--map-current-user', '/work/bootstrap-output/work-dir/pydantic_core-2.18.4/build-3.11.7/bin/python3', '-m', 'pip', '-vvv', '--disable-pip-version-check', 'wheel', '--no-build-isolation', '--only-binary', ':all:', '--wheel-dir', '/work/bootstrap-output/wheels-repo/build', '--no-deps', '--index-url', 'http://localhost:45837/simple/', '--log', '/work/bootstrap-output/work-dir/pydantic_core-2.18.4/build.log', '/work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4'] failed with Created temporary directory: /tmp/pip-build-tracker-q7oc2ftp
   Initialized build tracking at /tmp/pip-build-tracker-q7oc2ftp
   Created build tracker: /tmp/pip-build-tracker-q7oc2ftp
   Entered build tracker: /tmp/pip-build-tracker-q7oc2ftp
   Created temporary directory: /tmp/pip-wheel-_ol69xlg
   Created temporary directory: /tmp/pip-ephem-wheel-cache-d13st1qz
   Looking in indexes: http://localhost:45837/simple/
   Processing /work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   Added file:///work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4 to build tracker '/tmp/pip-build-tracker-q7oc2ftp'
   Created temporary directory: /tmp/pip-modern-metadata-q7vigowe
   Preparing metadata (pyproject.toml): started
   Running command Preparing metadata (pyproject.toml)
   📦 Including license file "/work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4/LICENSE"
   🍹 Building a mixed python/rust project
   🔗 Found pyo3 bindings
   🐍 Found CPython 3.11 at /work/bootstrap-output/work-dir/pydantic_core-2.18.4/build-3.11.7/bin/python3
   📡 Using build options features, bindings from pyproject.toml
   pydantic_core-2.18.4.dist-info
   Checking for Rust toolchain....
   Running `maturin pep517 write-dist-info --metadata-directory /tmp/pip-modern-metadata-q7vigowe --interpreter /work/bootstrap-output/work-dir/pydantic_core-2.18.4/build-3.11.7/bin/python3`
   Preparing metadata (pyproject.toml): finished with status 'done'
   Source in /work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4 has version 2.18.4, which satisfies requirement pydantic_core==2.18.4 from file:///work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   Removed pydantic_core==2.18.4 from file:///work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4 from build tracker '/tmp/pip-build-tracker-q7oc2ftp'
   Created temporary directory: /tmp/pip-unpack-ye9iobqx
   Created temporary directory: /tmp/pip-unpack-j0zwnxci
   Building wheels for collected packages: pydantic_core
   Created temporary directory: /tmp/pip-wheel-3o238ckb
   Destination directory: /tmp/pip-wheel-3o238ckb
   Building wheel for pydantic_core (pyproject.toml): started
   Running command Building wheel for pydantic_core (pyproject.toml)
   Running `maturin pep517 build-wheel -i /work/bootstrap-output/work-dir/pydantic_core-2.18.4/build-3.11.7/bin/python3 --compatibility off`
   📦 Including license file "/work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4/LICENSE"
   🍹 Building a mixed python/rust project
   🔗 Found pyo3 bindings
   🐍 Found CPython 3.11 at /work/bootstrap-output/work-dir/pydantic_core-2.18.4/build-3.11.7/bin/python3
   📡 Using build options features, bindings from pyproject.toml
   error: package `pydantic-core v2.18.4 (/work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4)` cannot be built because it requires rustc 1.76 or newer, while the currently active rustc version is 1.75.0

   💥 maturin failed
      Caused by: Failed to build a native library through cargo
      Caused by: Cargo build finished with "exit status: 101": `env -u CARGO PYO3_ENVIRONMENT_SIGNATURE="cpython-3.11-64bit" PYO3_PYTHON="/work/bootstrap-output/work-dir/pydantic_core-2.18.4/build-3.11.7/bin/python3" PYTHON_SYS_EXECUTABLE="/work/bootstrap-output/work-dir/pydantic_core-2.18.4/build-3.11.7/bin/python3" "cargo" "rustc" "--features" "pyo3/extension-module" "--message-format" "json-render-diagnostics" "--manifest-path" "/work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4/Cargo.toml" "--release" "--lib" "--crate-type" "cdylib"`
   Error: command ['maturin', 'pep517', 'build-wheel', '-i', '/work/bootstrap-output/work-dir/pydantic_core-2.18.4/build-3.11.7/bin/python3', '--compatibility', 'off'] returned non-zero exit status 1
   error: subprocess-exited-with-error

   × Building wheel for pydantic_core (pyproject.toml) did not run successfully.
   │ exit code: 1
   ╰─> See above for output.

   note: This error originates from a subprocess, and is likely not a problem with pip.
   full command: /work/bootstrap-output/work-dir/pydantic_core-2.18.4/build-3.11.7/bin/python3 /work/bootstrap-output/work-dir/pydantic_core-2.18.4/build-3.11.7/lib/python3.11/site-packages/pip/_vendor/pyproject_hooks/_in_process/_in_process.py build_wheel /tmp/tmpamjy51ga
   cwd: /work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   Building wheel for pydantic_core (pyproject.toml): finished with status 'error'
   ERROR: Failed building wheel for pydantic_core
   Failed to build pydantic_core
   ERROR: Failed to build one or more wheels

Using the pre_built flag
~~~~~~~~~~~~~~~~~~~~~~~~

The important error embedded in that output is:

.. code-block:: console

   cannot be built because it requires rustc 1.76 or newer, while the currently active rustc version is 1.75.0

So, the version of the Rust compiler we have available in the builder image is
too old to use to build this version of ``pydantic-core``. Let's mark
``pydantic-core`` as pre-built and see if any of its installation dependencies
present similar issues.

To mark the package as pre-built, create a settings file using fromager's
canonical form of the package name::

  $ fromager canonicalize pydantic-core
  pydantic_core

.. code-block:: yaml
   :caption: overrides/settings/pydantic_core.yaml

   variants:
     cpu-ubi9:
       pre_built: true

Now when we re-run ``bootstrap``, we see that ``pydantic-core`` will be treated
as "pre-built", the wheel is downloaded from pypi.org, and the process completes
successfully.

.. code-block:: console
   :emphasize-lines: 14

   + podman run -it --rm --security-opt label=disable --volume ./bootstrap-output:/work/bootstrap-output:rw,exec --volume ./bootstrap-ccache:/var/cache/ccache:rw,exec --volume ././constraints.txt:/bootstrap-inputs/constraints.txt --volume ././requirements.txt:/bootstrap-inputs/requirements.txt wheels-builder fromager --constraints-file /bootstrap-inputs/constraints.txt --log-file=bootstrap-output/bootstrap.log --sdists-repo=bootstrap-output/sdists-repo --wheels-repo=bootstrap-output/wheels-repo --work-dir=bootstrap-output/work-dir bootstrap -r /bootstrap-inputs/requirements.txt
   logging debug information to bootstrap-output/bootstrap.log
   primary settings file: overrides/settings.yaml
   per-package settings dir: overrides/settings
   variant: cpu-ubi9
   patches dir: overrides/patches
   maximum concurrent jobs: None
   constraints file: /bootstrap-inputs/constraints.txt
   wheel server url:
   network isolation: True
   loading constraints from /bootstrap-inputs/constraints.txt
   bootstrapping 'cpu-ubi9' variant of [<Requirement('pydantic-core==2.18.4')>]
   no previous bootstrap data
   treating ['pydantic-core'] as pre-built wheels

   ...

   100%|██████████████████████████████████████████████████████████████████████████████████████████| 3/3 [00:07<00:00,  2.35s/pkg]
   removing prebuilt wheel pydantic_core-2.18.4-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl from download cache
   writing installation dependencies to /work/bootstrap-output/work-dir/constraints.txt

Iteratively debugging the build
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Since there are no other build issues, we can start working on making
``pydantic-core`` build. The error caused by the rust version is actually an
error in the build settings of ``pydantic-core`` that was `fixed in a later
release <https://github.com/pydantic/pydantic-core/pull/1316>`__. Until that
upstream fix is released, we can have fromager apply a similar patch.

Start by removing the settings with the ``pre-built`` flag to have fromager try
to build from source. Then add this patch file to change the ``rust-version``
setting:

.. literalinclude:: example/overrides/patches/pydantic_core-2.18.4/0001-rust-version.patch
   :caption: overrides/patches/pydantic_core-2.18.4/0001-rust-version.patch
   :emphasize-lines: 12-13

Then by running ``bootstrap.sh`` again, we can see the patch being applied

.. code-block:: console
   :emphasize-lines: 6

   ...

   pydantic-core: * handling toplevel requirement pydantic-core==2.18.4 []
   pydantic-core: new toplevel dependency pydantic-core==2.18.4 resolves to 2.18.4
   pydantic-core: preparing source for pydantic-core==2.18.4 from /work/bootstrap-output/sdists-repo/downloads/pydantic_core-2.18.4.tar.gz
   applying patch file overrides/patches/pydantic_core-2.18.4/0001-rust-version.patch to /work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   pydantic-core: updating vendored rust dependencies in /work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   pydantic-core: prepared source for pydantic-core==2.18.4 at /work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   pydantic-core: getting build system dependencies for pydantic-core==2.18.4 in /work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4

followed by the wheel being built successfully.

.. code-block:: console
   :emphasize-lines: 13

   pydantic-core: getting build backend dependencies for pydantic-core==2.18.4 in /work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   pydantic-core: getting build sdist dependencies for pydantic-core==2.18.4 in /work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   pydantic-core: adding ('pydantic-core', '2.18.4') to build order
   pydantic-core: preparing to build wheel for version 2.18.4
   created build environment in /work/bootstrap-output/work-dir/pydantic_core-2.18.4/build-3.11.7
   installed dependencies into build environment in /work/bootstrap-output/work-dir/pydantic_core-2.18.4/build-3.11.7
   pydantic-core: building source distribution in /work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   pydantic-core: built source distribution /work/bootstrap-output/sdists-repo/builds/pydantic_core-2.18.4.tar.gz
   pydantic-core: building wheel for pydantic-core==2.18.4 in /work/bootstrap-output/work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4 writing to /work/bootstrap-output/wheels-repo/build
   pydantic-core: Requires libraries: libc.so.6, libgcc_s.so.1, libm.so.6
   pydantic-core: added extra metadata and build tag (0, ''), wheel renamed from pydantic_core-2.18.4-cp311-cp311-linux_x86_64.whl to pydantic_core-2.18.4-0-cp311-cp311-linux_x86_64.whl
   pydantic-core: built wheel '/work/bootstrap-output/wheels-repo/build/pydantic_core-2.18.4-0-cp311-cp311-linux_x86_64.whl' in 0:03:53
   pydantic-core: built wheel for version 2.18.4: /work/bootstrap-output/wheels-repo/downloads/pydantic_core-2.18.4-0-cp311-cp311-linux_x86_64.whl

The :doc:`customization` section explains other techniques for changing the
build inputs to ensure packages build properley. The collection of wheels you
want to build may have different build-time issues, but you can use this
iterative approach to work your way though them until they all build.
