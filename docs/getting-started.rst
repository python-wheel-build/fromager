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
3. Run ``fromager bootstrap``, passing your ```requirements.txt``` and
   ``constraints.txt``, to try to build the collection.
4. When a package fails to build, create a settings file and mark it as
   pre-built. This lets you move through the full set of dependencies quickly,
   and build a list of the problematic packages.
5. When the build completes, review the set of pre-built packages and
   iteratively "fix" each one so that you are able to build it. Typical reasons
   for failure include missing system dependencies, packages that have no source
   distributions, and packages for which wheels cannot be built from the source
   distribution because it is incomplete.

.. note::

   It may be useful to use a container to run fromager so you can use the
   `Containerfile` to manage the build-time dependencies. Refer to
   :doc:`how-tos/containers` for more details.

Example Bootstrap Session
-------------------------

We will use `pydantic-core` to demonstrate debugging and fixing a build failure.

We can start with a ``requirements.txt`` file:

.. literalinclude:: example/requirements.txt
   :caption: requirements.txt

Then we can use the ``fromager bootstrap`` script in the ``docs/example`` directory to
build and test the image:

The output below is redacted for brevity. Missing sections are replaced with ``...``.

.. code-block:: console
   :emphasize-lines: 56-

   $ fromager bootstrap --requirements-file ./docs/example/requirements.txt

   11:17:49 INFO primary settings file: overrides/settings.yaml
   11:17:49 INFO per-package settings dir: overrides/settings
   11:17:49 INFO variant: cpu
   11:17:49 INFO patches dir: overrides/patches
   11:17:49 INFO maximum concurrent jobs: None
   11:17:49 INFO constraints file: None
   11:17:49 INFO network isolation: False
   11:17:49 INFO cache wheel server url: None
   11:17:49 INFO bootstrapping 'cpu' variant of [<Requirement('pydantic-core==2.18.4')>]
   11:17:49 INFO no previous bootstrap data
   11:17:49 INFO build all missing wheels
   0%|                                                                                                                                                  | 0/2 [00:00<?, ?pkg/s]11:17:50 INFO resolving top-level dependencies before building
   11:17:50 INFO pydantic-core: looking for candidates for <Requirement('pydantic-core==2.18.4')>
   11:17:51 INFO pydantic-core: selecting <pydantic-core==2.18.4>
   11:17:51 INFO pydantic-core: successfully resolved <Requirement('pydantic-core==2.18.4')>
   11:17:51 INFO pydantic-core: pydantic-core==2.18.4 resolves to 2.18.4
   11:17:51 INFO pydantic-core: looking for candidates for <Requirement('pydantic-core==2.18.4')>
   11:17:52 INFO pydantic-core: selecting <pydantic-core==2.18.4>
   11:17:52 INFO pydantic-core: successfully resolved <Requirement('pydantic-core==2.18.4')>
   11:17:52 INFO pydantic-core: new toplevel dependency pydantic-core==2.18.4 resolves to 2.18.4
   11:17:52 INFO pydantic-core: looking for existing wheel for version 2.18.4 with build tag () in ./wheels-repo/build
   11:17:52 INFO pydantic-core: looking for existing wheel for version 2.18.4 with build tag () in ./wheels-repo/downloads
   11:17:52 INFO pydantic-core: checking if wheel was already uploaded to http://localhost:55873/simple/
   11:17:52 INFO pydantic-core: looking for candidates for <Requirement('pydantic-core==2.18.4')>
   11:17:52 INFO pydantic-core: did not find wheel for 2.18.4 in http://localhost:55873/simple/
   11:17:52 INFO pydantic-core: downloading source for pydantic-core==2.18.4
   11:17:52 INFO pydantic-core: saved ./sdists-repo/downloads/pydantic_core-2.18.4.tar.gz
   11:17:52 INFO pydantic-core: preparing source for pydantic-core==2.18.4 from ./sdists-repo/downloads/pydantic_core-2.18.4.tar.gz
   11:17:52 INFO pydantic-core: updating vendored rust dependencies in ./work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   11:17:54 INFO pydantic-core: prepared source for pydantic-core==2.18.4 at ./work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   11:17:54 INFO pydantic-core: created build environment in ./work-dir/pydantic_core-2.18.4/build-3.11.13
   11:17:54 INFO pydantic-core: getting build system dependencies for pydantic-core==2.18.4 in ./work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   11:17:54 INFO maturin: looking for candidates for <Requirement('maturin<2,>=1')>
   11:17:54 INFO maturin: selecting <maturin==1.9.0>

   ...

   88%|███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████                 | 14/16 [01:20<00:14,  7.30s/pkg]11:19:11 INFO pydantic-core: installed dependencies {<Requirement('maturin<2,>=1')>, <Requirement('typing-extensions!=4.7.0,>=4.6.0')>} into build environment in ./work-dir/pydantic_core-2.18.4/build-3.11.13
   11:19:11 INFO pydantic-core: getting build backend dependencies for pydantic-core==2.18.4 in ./work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   11:19:11 INFO pydantic-core: getting build sdist dependencies for pydantic-core==2.18.4 in ./work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   11:19:11 INFO pydantic-core: building cpu source distribution for pydantic-core==2.18.4 in ./work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4
   11:19:14 INFO pydantic-core: built source distribution ./sdists-repo/builds/pydantic-core-2.18.4.tar.gz
   11:19:14 INFO pydantic-core: starting build of toplevel dependency pydantic-core==2.18.4 (2.18.4) for cpu
   11:19:14 INFO pydantic-core: building cpu wheel for pydantic-core==2.18.4 in ./work-dir/pydantic_core-2.18.4/pydantic_core-2.18.4 writing to ./wheels-repo/build
   11:19:56 INFO pydantic-core: added extra metadata and build tag (0, ''), wheel renamed from pydantic_core-2.18.4-cp311-cp311-macosx_11_0_arm64.whl to pydantic_core-2.18.4-0-cp311-cp311-macosx_11_0_arm64.whl
   11:19:56 INFO pydantic-core: adding pydantic_core-2.18.4-0-cp311-cp311-macosx_11_0_arm64.whl to local wheel server
   11:19:56 INFO pydantic-core: built wheel for version 2.18.4: ./wheels-repo/downloads/pydantic_core-2.18.4-0-cp311-cp311-macosx_11_0_arm64.whl
   11:19:56 INFO pydantic-core: getting installation dependencies from ./wheels-repo/downloads/pydantic_core-2.18.4-0-cp311-cp311-macosx_11_0_arm64.whl
   11:19:56 INFO pydantic-core: adding ('pydantic-core', '2.18.4') to build order
   11:19:56 INFO typing-extensions: looking for candidates for <Requirement('typing-extensions!=4.7.0,>=4.6.0')>
   11:19:56 INFO typing-extensions: selecting <typing-extensions==4.14.0>
   11:19:56 INFO typing-extensions: successfully resolved <Requirement('typing-extensions!=4.7.0,>=4.6.0')>
   94%|████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████        | 16/17 [02:06<00:07,  7.92s/pkg]
   11:19:56 INFO writing installation dependencies to ./work-dir/constraints.txt
   11:19:56 INFO Bootstrapping flit_core==3.12.0 took 0:00:01 total, 0:00:00 to resolve source, 0:00:00 to download source, 0:00:00 to prepare source, 0:00:00 to build sdist, 0:00:00 to add extra metadata to wheels, 0:00:01 to build wheels
   11:19:56 INFO Bootstrapping maturin==1.9.0 took 0:00:58 total, 0:00:00 to resolve source, 0:00:00 to download source, 0:00:08 to prepare source, 0:00:12 to build sdist, 0:00:01 to add extra metadata to wheels, 0:00:37 to build wheels
   11:19:56 INFO Bootstrapping packaging==25.0 took 0:00:01 total, 0:00:00 to resolve source, 0:00:00 to download source, 0:00:00 to prepare source, 0:00:00 to build sdist, 0:00:00 to add extra metadata to wheels, 0:00:00 to build wheels
   11:19:56 INFO Bootstrapping pydantic-core==2.18.4 took 0:00:49 total, 0:00:02 to resolve source, 0:00:00 to download source, 0:00:02 to prepare source, 0:00:03 to build sdist, 0:00:00 to add extra metadata to wheels, 0:00:42 to build wheels
   11:19:56 INFO Bootstrapping semantic_version==2.10.0 took 0:00:01 total, 0:00:00 to resolve source, 0:00:00 to download source, 0:00:00 to prepare source, 0:00:00 to build sdist, 0:00:00 to add extra metadata to wheels, 0:00:01 to build wheels
   11:19:56 INFO Bootstrapping setuptools-rust==1.11.1 took 0:00:01 total, 0:00:00 to resolve source, 0:00:00 to download source, 0:00:00 to prepare source, 0:00:00 to build sdist, 0:00:00 to add extra metadata to wheels, 0:00:01 to build wheels
   11:19:56 INFO Bootstrapping setuptools==80.9.0 took 0:00:04 total, 0:00:00 to resolve source, 0:00:00 to download source, 0:00:00 to prepare source, 0:00:01 to build sdist, 0:00:00 to add extra metadata to wheels, 0:00:02 to build wheels
   11:19:56 INFO Bootstrapping setuptools_scm==8.3.1 took 0:00:01 total, 0:00:00 to resolve source, 0:00:00 to download source, 0:00:00 to prepare source, 0:00:00 to build sdist, 0:00:00 to add extra metadata to wheels, 0:00:01 to build wheels
   11:19:56 INFO Bootstrapping typing-extensions==4.14.0 took 0:00:01 total, 0:00:00 to resolve source, 0:00:00 to download source, 0:00:00 to prepare source, 0:00:00 to build sdist, 0:00:00 to add extra metadata to wheels, 0:00:00 to build wheels

As each dependency is built, fromager will show output from the build process
and progress information. At the end of the build, fromager shows the lsit of
packages that were built and how long each step took.
