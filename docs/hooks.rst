Fromager hooks
==============

Dependency hooks
----------------

.. py:currentmodule:: fromager.dependencies

.. autofromagerhook:: default_get_build_system_dependencies

.. autofromagerhook:: default_get_build_backend_dependencies

.. autofromagerhook:: default_get_build_sdist_dependencies


Finder hooks
------------

.. py:currentmodule:: fromager.finders

.. autofromagerhook:: default_expected_source_archive_name

.. autofromagerhook:: default_expected_source_directory_name


Resolver hooks
--------------

.. currentmodule:: fromager.resolver

.. autofromagerhook:: default_resolver_provider


Source hooks
------------

.. currentmodule:: fromager.sources

.. autofromagerhook:: default_resolve_source

.. autofromagerhook:: default_download_source

.. autofromagerhook:: default_prepare_source

.. autofromagerhook:: default_build_sdist


Wheel hooks
-----------

.. currentmodule:: fromager.wheels

.. autofromagerhook:: default_build_wheel

.. autofromagerhook:: default_add_extra_metadata_to_wheels


Additional types
----------------

.. autoclass:: fromager.build_environment.BuildEnvironment
.. autoclass:: fromager.context.WorkContext
.. autoclass:: fromager.resolver.PyPIProvider
.. autoclass:: fromager.resolver.GenericProvider
.. autoclass:: fromager.resolver.GitHubTagProvider
.. autofunction:: fromager.sources.prepare_new_source
