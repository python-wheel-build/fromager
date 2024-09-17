Fromager hooks and override plugins
===================================

For more complex customization requirements than are supported by the
configuration file, create an override plugin.

Plugins are registered using `entry
points <https://packaging.python.org/en/latest/specifications/entry-points/>`__
so they can be discovered and loaded at runtime. In `pyproject.toml`,
configure the entry point in the
``project.entry-points."fromager.project_overrides"`` namespace to
link the :ref:`canonical distribution name <canonical-distribution-names>`
to an importable module.

.. code-block:: toml
    :caption: pyproject.toml snippet

    [project.entry-points."fromager.project_overrides"]
    flit_core = "package_plugins.flit_core"
    pyarrow = "package_plugins.pyarrow"
    torch = "package_plugins.torch"
    triton = "package_plugins.triton"

The plugins are treated as providing overriding implementations of
functions with default implementations, so it is only necessary to
implement the functions needed to make it possible to build the
package.

Dependency hooks
----------------

.. py:currentmodule:: fromager.dependencies

.. autofromagerhook:: default_get_build_system_dependencies

    The ``get_build_system_dependencies()`` function should return the PEP 517
    build dependencies for a package.

    The arguments are the ``WorkContext``, the ``Requirement`` being evaluated,
    and the ``Path`` to the root of the source tree.

    The return value is an iterable of requirement specification strings for
    build system dependencies for the package. The caller is responsible for
    evaluating the requirements with the current build environment settings to
    determine if they are actually needed.

.. autofromagerhook:: default_get_build_backend_dependencies

    The ``get_build_backend_dependencies()`` function should return the PEP
    517 build dependencies for a package.

    The arguments are the ``WorkContext``, the ``Requirement`` being
    evaluated, and the `Path` to the root of the source tree.

    The return value is an iterable of requirement specification strings
    for build backend dependencies for the package. The caller is
    responsible for evaluating the requirements with the current build
    environment settings to determine if they are actually needed.

.. autofromagerhook:: default_get_build_sdist_dependencies

    The ``get_build_sdist_dependencies()`` function should return the PEP 517
    dependencies for building the source distribution for a package.

    The return value is an iterable of requirement specification strings
    for build backend dependencies for the package. The caller is
    responsible for evaluating the requirements with the current build
    environment settings to determine if they are actually needed.


Finder hooks
------------

.. py:currentmodule:: fromager.finders

.. autofromagerhook:: default_expected_source_archive_name

    The ``expected_source_archive_name()`` function is used to re-discover a
    source archive downloaded by a previous step, especially if the
    filename does not match the standard naming scheme for an sdist.

    The arguments are the ``Requirement`` being evaluated and the version to
    look for.

    The return value should be a string with the base filename (no paths)
    for the archive.

.. autofromagerhook:: default_expected_source_directory_name

    The ``expected_source_directory_name()`` function is used to re-discover
    the location of a source tree prepared by a previous step, especially
    if the name does not match the standard naming scheme for an sdist.

    The arguments are the ``Requirement`` being evaluated and the version to
    look for.

    The return value should be a string with the name of the source root
    directory relative to the ``ctx.work_dir`` where it was prepared.

Resolver hooks
--------------

.. currentmodule:: fromager.resolver

.. autofromagerhook:: default_resolver_provider

    The ``get_resolver_provider()`` function allows an override to change
    the way requirement specifications are converted to fixed
    versions. The default implementation looks for published versions on a
    Python package index. Most overrides do not need to implement this
    hook unless they are building versions of packages not released to
    https://pypi.org.

    For examples, refer to ``fromager.resolver.PyPIProvider`` and
    ``fromager.resolver.GitHubTagProvider``.

    The arguments are the ``WorkContext``, the ``Requirement`` being
    evaluated, a boolean indicating whether source distributions should be
    included, a boolean indicating whether built wheels should be
    included, and the URL for the sdist server.

    The return value must be an instance of a class that implements the
    ``resolvelib.providers.AbstractProvider`` API.

    The expectation is that it acts as an engine for any sort of package resolution
    whether it is for wheels or sources. The provider can
    therefore use any value as the "URL" that will help it decide what to
    download. For example, the ``GitHubTagProvider`` returns the actual tag
    name in case that is different from the version number encoded within
    that tag name.

    The ``GenericProvider`` is a convenient base class, or can be instantiated
    directly if given a ``version_source`` callable that returns an iterator of
    version values as ``str`` or ``Version`` objects.

    .. code-block:: python

        from fromager import resolver

        VERSION_MAP = {'1.0': 'first-release', '2.0': 'second-release'}

        def _version_source(
                identifier: str,
                requirements: resolver.RequirementsMap,
                incompatibilities: resolver.CandidatesMap,
            ) -> typing.Iterable[Version]:
            return VERSION_MAP.keys()


        def get_resolver_provider(ctx, req, include_sdists, include_wheels, sdist_server_url):
            return resolver.GenericProvider(version_source=_version_source, constraints=ctx.constraints)

Source hooks
------------

.. currentmodule:: fromager.sources

.. autofromagerhook:: default_resolve_source

    The ``resolve_source()`` function is responsible for resolving a
    requirement and acquiring the source for that version of a
    package. The default is to use pypi.org to resolve the requirement.

    The arguments are the ``WorkContext``, the ``Requirement`` being
    evaluated, and the URL to the sdist index.

    The return value is ``Tuple[str, Version]`` where the first member is
    the url from which the source can be downloaded and the second member
    is the version of the resolved package.

.. autofromagerhook:: default_download_source

    The ``download_source()`` function is responsible for downloading the
    source from a URL.

    The arguments are the ``WorkContext``, the ``Requirement`` being
    evaluated, version of the package being downloaded, the URL
    from which the source can be downloaded as returned by ``resolve_source``,
    and the output directory in which the source should be downloaded.

    The return value should be a ``pathlib.Path`` file path to the downloaded source.

.. autofromagerhook:: default_prepare_source

    The ``prepare_source()`` function is responsible for setting up a tree
    of source files in a format that is ready to be built. The default
    implementation unpacks the source archive and applies patches.

    The arguments are the ``WorkContext``, the ``Requirement`` being
    evaluated, the ``Path`` to the source archive, and the version.

    The return value should be the ``Path`` to the root of the source tree,
    ideally inside the ``ctx.work_dir`` directory.

.. autofromagerhook:: default_build_sdist

    The ``build_sdist()`` function is responsible for creating a new source
    distribution from the prepared source tree and placing it in ``ctx.sdists_build``.

    The arguments are the ``WorkContext``, the ``Requirement`` being evaluated, and the
    `Path` to the root of the source tree.

    The return value is the ``Path`` to the newly created source distribution.


Wheel hooks
-----------

.. currentmodule:: fromager.wheels

.. autofromagerhook:: default_build_wheel

    The ``build_wheel()`` function is responsible for creating a wheel from
    the prepared source tree and placing it in ``ctx.wheels_build``. The
    default implementation invokes ``pip wheel`` in a temporary directory
    and passes the path to the source tree as argument.

    The arguments are the ``WorkContext``, the ``Path`` to a virtualenv
    prepared with the build dependencies, a ``dict`` with extra environment
    variables to pass to the build, the ``Requirement`` being evaluated, and
    the ``Path`` to the root of the source tree.

    The return value is ignored.

.. autofromagerhook:: default_add_extra_metadata_to_wheels

    The ``add_extra_metadata_to_wheels()`` function is responsible to return any
    data the user would like to include in the wheels that fromager builds. This
    data will be added to the ``fromager-build-settings`` file under the
    ``.dist-info`` directory of the wheels. This file already contains the
    settings used to build that package.

    The arguments available are ``WorkContext``, ``Requirement`` being
    evaluated, the resolved ``Version`` of that requirement, a ``dict`` with extra
    environment variables, a ``Path`` to the root directory of the source
    distribution and a ``Path`` to the ``.dist-info`` directory of the wheel.

    The return value must be a ``dict``, otherwise it will be ignored.


Additional types
----------------

.. autoclass:: fromager.build_environment.BuildEnvironment
.. autoclass:: fromager.context.WorkContext
.. autoclass:: fromager.resolver.PyPIProvider
.. autoclass:: fromager.resolver.GenericProvider
.. autoclass:: fromager.resolver.GitHubTagProvider
.. autofunction:: fromager.sources.prepare_new_source
