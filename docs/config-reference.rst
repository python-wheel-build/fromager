Configuration Reference
=======================

Per-package Settings
--------------------

Settings for individual packages can be placed in the `overrides/settings/`
directory. Files should be named using the canonicalized name of the package.
For example `flash_attn.yaml`.

.. autopydantic_model:: fromager.packagesettings.PackageSettings

.. autopydantic_model:: fromager.packagesettings.BuildOptions

.. autopydantic_model:: fromager.packagesettings.DownloadSource

.. autopydantic_model:: fromager.packagesettings.ResolverDist

.. autopydantic_model:: fromager.packagesettings.ProjectOverride

Global Settings
---------------

The global changelogs can be placed in `overrides/settings.yaml`.

If you prefer managing a single settings file, per-package settings can also be
kept in this file.

.. autopydantic_model:: fromager.packagesettings.SettingsFile
