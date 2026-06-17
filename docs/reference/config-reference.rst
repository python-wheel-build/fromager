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

.. autopydantic_model:: fromager.packagesettings.PurlConfig

.. autopydantic_model:: fromager.packagesettings.SbomSettings

Source Resolver
^^^^^^^^^^^^^^^

.. autopydantic_model:: PyPISDistResolver
   :inherited-members: AbstractPyPIResolver, CooldownMixin

.. autopydantic_model:: PyPIPrebuiltResolver
   :inherited-members: AbstractPyPIResolver, CooldownMixin

.. autopydantic_model:: PyPIDownloadResolver
   :inherited-members: AbstractPyPIResolver, CooldownMixin

.. autopydantic_model:: PyPIGitResolver
   :inherited-members: AbstractPyPIResolver, CooldownMixin

.. autopydantic_model:: VersionMapGitResolver

.. autopydantic_model:: GitHubTagDownloadResolver
   :inherited-members: AbstractGitSourceResolver, CooldownMixin

.. autopydantic_model:: GitHubTagCloneResolver
   :inherited-members: AbstractGitSourceResolver, CooldownMixin

.. autopydantic_model:: GitLabTagDownloadResolver
   :inherited-members: AbstractGitSourceResolver, CooldownMixin

.. autopydantic_model:: GitLabTagCloneResolver
   :inherited-members: AbstractGitSourceResolver, CooldownMixin

.. autopydantic_model:: NotAvailableResolver

.. autopydantic_model:: HookResolver

.. autoclass:: BuildSDist

   .. autoattribute:: pep517
   .. autoattribute:: tarball


Global Settings
---------------

The global changelogs can be placed in `overrides/settings.yaml`.

If you prefer managing a single settings file, per-package settings can also be
kept in this file.

.. autopydantic_model:: fromager.packagesettings.SettingsFile
