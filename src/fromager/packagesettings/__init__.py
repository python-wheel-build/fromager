"""Package settings for Fromager build system."""

from ._hooks import default_update_extra_environ, get_extra_environ
from ._models import (
    BuildOptions,
    DownloadSource,
    GitOptions,
    PackageSettings,
    ProjectOverride,
    ResolverDist,
    VariantInfo,
)
from ._pbi import PackageBuildInfo
from ._settings import Settings, SettingsFile
from ._templates import substitute_template
from ._typedefs import (
    MODEL_CONFIG,
    Annotations,
    BuildDirectory,
    EnvKey,
    EnvVars,
    GlobalChangelog,
    Package,
    PackageVersion,
    PatchMap,
    RawAnnotations,
    Template,
    Variant,
    VariantChangelog,
)

__all__ = (
    "MODEL_CONFIG",
    "Annotations",
    "BuildDirectory",
    "BuildOptions",
    "DownloadSource",
    "EnvKey",
    "EnvVars",
    "GitOptions",
    "GlobalChangelog",
    "Package",
    "PackageBuildInfo",
    "PackageSettings",
    "PackageVersion",
    "PatchMap",
    "ProjectOverride",
    "RawAnnotations",
    "ResolverDist",
    "Settings",
    "SettingsFile",
    "Template",
    "Variant",
    "VariantChangelog",
    "VariantInfo",
    "default_update_extra_environ",
    "get_extra_environ",
    "substitute_template",
)
