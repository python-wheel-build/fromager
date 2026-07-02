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
   :members: download_kind, supports_override_hooks

.. autopydantic_model:: PyPIPrebuiltResolver
   :inherited-members: AbstractPyPIResolver, CooldownMixin
   :members: download_kind, supports_override_hooks

.. autopydantic_model:: PyPIDownloadResolver
   :inherited-members: AbstractPyPIResolver, CooldownMixin
   :members: download_kind, supports_override_hooks

.. autopydantic_model:: PyPIGitResolver
   :inherited-members: AbstractPyPIResolver, CooldownMixin
   :members: download_kind, supports_override_hooks

.. autopydantic_model:: GitHubTagDownloadResolver
   :inherited-members: AbstractGitSourceResolver, CooldownMixin
   :members: download_kind, supports_override_hooks

.. autopydantic_model:: GitHubTagCloneResolver
   :inherited-members: AbstractGitSourceResolver, CooldownMixin
   :members: download_kind, supports_override_hooks

.. autopydantic_model:: GitLabTagDownloadResolver
   :inherited-members: AbstractGitSourceResolver, CooldownMixin
   :members: download_kind, supports_override_hooks

.. autopydantic_model:: GitLabTagCloneResolver
   :inherited-members: AbstractGitSourceResolver, CooldownMixin
   :members: download_kind, supports_override_hooks

.. autopydantic_model:: NotAvailableResolver
   :members: download_kind, supports_override_hooks

.. autopydantic_model:: HookSDistResolver
   :inherited-members: AbstractHookResolver, CooldownMixin
   :members: download_kind, supports_override_hooks

.. autopydantic_model:: HookPrebuiltResolver
   :inherited-members: AbstractHookResolver, CooldownMixin
   :members: download_kind, supports_override_hooks

.. autoclass:: BuildSDist

   .. autoattribute:: pep517
   .. autoattribute:: tarball

.. autoclass:: DownloadKind

   .. autoattribute:: sdist
   .. autoattribute:: tarball
   .. autoattribute:: prebuilt_wheel
   .. autoattribute:: git_checkout
   .. autoattribute:: any_source
   .. autoattribute:: not_available


Global Settings
---------------

The global changelogs can be placed in `overrides/settings.yaml`.

If you prefer managing a single settings file, per-package settings can also be
kept in this file.

.. autopydantic_model:: fromager.packagesettings.SettingsFile
