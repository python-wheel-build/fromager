Configuration Reference
=======================

.. currentmodule:: fromager.packagesettings

Per-package Settings
--------------------

Settings for individual packages can be placed in the `overrides/settings/`
directory. Files should be named using the canonicalized name of the package.
For example `flash_attn.yaml`.

.. autopydantic_model:: fromager.packagesettings.PackageSettings

.. autopydantic_model:: fromager.packagesettings.BuildOptions

.. autopydantic_model:: fromager.packagesettings.DownloadSource

.. autopydantic_model:: fromager.packagesettings.GitOptions

.. autopydantic_model:: fromager.packagesettings.ResolverDist

.. autopydantic_model:: fromager.packagesettings.ProjectOverride

Source Resolver
^^^^^^^^^^^^^^^

.. autopydantic_model:: fromager.packagesettings.PyPISDistResolver

.. autopydantic_model:: fromager.packagesettings.PyPIPrebuiltResolver

.. autopydantic_model:: fromager.packagesettings.PyPIDownloadResolver

.. autopydantic_model:: fromager.packagesettings.PyPIGitResolver

.. autopydantic_model:: fromager.packagesettings.GithubSourceResolver
   :inherited-members: AbstractGitSourceResolver

.. autopydantic_model:: fromager.packagesettings.GitlabSourceResolver
   :inherited-members: AbstractGitSourceResolver

.. autoclass:: fromager.packagesettings.BuildSDist

   .. autoattribute:: pep517
   .. autoattribute:: tarball

.. autoclass:: fromager.resolver.RetrieveMethod

   .. autoattribute:: tarball
   .. autoattribute:: git_https
   .. autoattribute:: git_ssh

Global Settings
---------------

The global changelogs can be placed in `overrides/settings.yaml`.

If you prefer managing a single settings file, per-package settings can also be
kept in this file.

.. autopydantic_model:: fromager.packagesettings.SettingsFile
