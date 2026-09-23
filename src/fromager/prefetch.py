"""Create and consume self-contained prefetch bundles."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.metadata
import json
import os
import pathlib
import platform
import shutil
import sys
import sysconfig
import tarfile
import tempfile
import typing

import pydantic
from packaging.requirements import Requirement
from packaging.utils import (
    InvalidSdistFilename,
    canonicalize_name,
    parse_sdist_filename,
)
from packaging.version import Version

from . import context, downloads, finders, tarballs

MANIFEST_FILENAME = "manifest.json"
FORMAT_VERSION: typing.Literal[1] = 1
_GENERATED_SOURCE_FILES = frozenset(
    {
        "build-backend-requirements.txt",
        "build-meta.json",
        "build-sdist-requirements.txt",
        "build-system-requirements.txt",
        "requirements.txt",
    }
)
_GENERATED_SOURCE_DIRECTORIES = frozenset(
    {"__pycache__", "_skbuild", "build", "target"}
)


def _exact_requirement_coordinate(requirement: str) -> tuple[str, str]:
    parsed = Requirement(requirement)
    specifiers = list(parsed.specifier)
    if (
        parsed.url
        or len(specifiers) != 1
        or specifiers[0].operator != "=="
        or "*" in specifiers[0].version
    ):
        raise ValueError(f"build requirement is not an exact pin: {requirement}")
    return canonicalize_name(parsed.name), specifiers[0].version


class PrefetchArtifact(pydantic.BaseModel):
    """Describe one file stored in a prefetch bundle."""

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    path: str
    sha256: str = pydantic.Field(pattern=r"^[0-9a-f]{64}$")
    size: int = pydantic.Field(ge=0)

    @pydantic.field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        """Require a safe path relative to the bundle root."""
        path = pathlib.PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"invalid prefetch artifact path {value!r}")
        return value


class PrefetchPackage(pydantic.BaseModel):
    """Describe the prepared artifact for one package build."""

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    dist: str
    version: str
    prebuilt: bool
    artifact: PrefetchArtifact
    build_requirements: tuple[str, ...] = ()

    @pydantic.model_validator(mode="after")
    def validate_artifact_type(self) -> PrefetchPackage:
        """Require a wheel for prebuilt packages and a source archive otherwise."""
        if self.prebuilt and not self.artifact.path.endswith(".whl"):
            raise ValueError(f"prebuilt package {self.dist} does not reference a wheel")
        if not self.prebuilt and not self.artifact.path.endswith((".tar.gz", ".zip")):
            raise ValueError(
                f"source package {self.dist} does not reference a source archive"
            )
        for requirement in self.build_requirements:
            _exact_requirement_coordinate(requirement)
        return self


class PrefetchWheel(pydantic.BaseModel):
    """Describe an exact wheel available to offline build environments."""

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    dist: str
    version: str
    artifact: PrefetchArtifact


class PrefetchManifest(pydantic.BaseModel):
    """Describe all inputs stored in a prefetch bundle."""

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    format_version: typing.Literal[1] = FORMAT_VERSION
    fromager_version: str
    python_version: str
    python_implementation: str
    platform: str
    variant: str
    settings_fingerprint: str = pydantic.Field(pattern=r"^[0-9a-f]{64}$")
    graph: PrefetchArtifact
    build_order: PrefetchArtifact
    constraints: PrefetchArtifact | None = None
    merged_constraints: PrefetchArtifact | None = None
    packages: tuple[PrefetchPackage, ...]
    wheels: tuple[PrefetchWheel, ...]

    @pydantic.model_validator(mode="after")
    def validate_package_keys(self) -> PrefetchManifest:
        """Reject duplicate package and version records."""
        seen: set[tuple[str, str]] = set()
        for package in self.packages:
            key = (canonicalize_name(package.dist), package.version)
            if key in seen:
                raise ValueError(f"duplicate prefetch package {key[0]}=={key[1]}")
            seen.add(key)
        return self


@dataclasses.dataclass(frozen=True)
class PrefetchBundle:
    """Provide validated access to a loaded prefetch bundle."""

    root: pathlib.Path
    manifest: PrefetchManifest
    _verified: set[str] = dataclasses.field(
        default_factory=set,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def build_order_file(self) -> pathlib.Path:
        """Return the validated build-order file."""
        return self.artifact_path(self.manifest.build_order)

    @property
    def graph_file(self) -> pathlib.Path:
        """Return the validated dependency graph file."""
        return self.artifact_path(self.manifest.graph)

    @property
    def constraints_file(self) -> pathlib.Path | None:
        """Return input constraints captured from the prefetch run, when present."""
        artifact = self.manifest.merged_constraints
        return self.artifact_path(artifact) if artifact is not None else None

    @property
    def wheelhouse_dirs(self) -> tuple[pathlib.Path, ...]:
        """Return local directories containing prefetched wheels."""
        directories = {
            self.artifact_path(wheel.artifact).parent for wheel in self.manifest.wheels
        }
        return tuple(sorted(directories))

    @property
    def package_coordinates(self) -> tuple[tuple[str, str], ...]:
        """Return package names and versions recorded in the bundle."""
        return tuple(
            (package.dist, package.version) for package in self.manifest.packages
        )

    def artifact_path(self, artifact: PrefetchArtifact) -> pathlib.Path:
        """Resolve an artifact path inside the bundle."""
        path = (self.root / artifact.path).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"prefetch artifact escapes bundle root: {artifact.path}")
        return path

    def package_artifact(
        self,
        dist: str,
        version: str,
        *,
        prebuilt: bool,
    ) -> pathlib.Path:
        """Return the prepared artifact for a package build."""
        name = canonicalize_name(dist)
        for package in self.manifest.packages:
            if (
                canonicalize_name(package.dist) == name
                and package.version == version
                and package.prebuilt == prebuilt
            ):
                return self.verify_artifact(package.artifact)
        raise KeyError(
            f"prefetch bundle has no {'wheel' if prebuilt else 'source archive'} "
            f"for {name}=={version}"
        )

    def build_requirements(self, dist: str, version: str) -> set[Requirement]:
        """Return exact requirements for one package's build environment."""
        package = self._package(dist, version)
        requirements = {Requirement(value) for value in package.build_requirements}
        for requirement in requirements:
            self._verify_wheel(requirement)
        return requirements

    def verify_artifact(self, artifact: PrefetchArtifact) -> pathlib.Path:
        """Verify and return one artifact path."""
        filename = self.artifact_path(artifact)
        if artifact.path in self._verified:
            return filename
        if not filename.is_file():
            raise FileNotFoundError(f"prefetch artifact is missing: {filename}")
        if filename.stat().st_size != artifact.size:
            raise ValueError(f"prefetch artifact has wrong size: {filename}")
        if _sha256(filename) != artifact.sha256:
            raise ValueError(f"prefetch artifact has wrong SHA-256: {filename}")
        self._verified.add(artifact.path)
        return filename

    def validate_configuration(self, ctx: context.WorkContext) -> None:
        """Verify that build settings match the prefetch environment."""
        actual = configuration_fingerprint(ctx, self.package_coordinates)
        if self.manifest.settings_fingerprint != actual:
            raise ValueError(
                "prefetch settings and patches do not match the build configuration"
            )

    def _package(self, dist: str, version: str) -> PrefetchPackage:
        name = canonicalize_name(dist)
        for package in self.manifest.packages:
            if canonicalize_name(package.dist) == name and package.version == version:
                return package
        raise KeyError(f"prefetch bundle has no package {name}=={version}")

    def _verify_wheel(self, requirement: Requirement) -> pathlib.Path:
        name, version = _exact_requirement_coordinate(str(requirement))
        for wheel in self.manifest.wheels:
            if canonicalize_name(wheel.dist) == name and wheel.version == version:
                return self.verify_artifact(wheel.artifact)
        raise KeyError(f"prefetch bundle has no wheel for {name}=={version}")


def _sha256(filename: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with filename.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def configuration_fingerprint(
    ctx: context.WorkContext,
    packages: typing.Iterable[tuple[str, str]],
) -> str:
    """Fingerprint settings, patches, and plugins that influence build output."""
    digest = hashlib.sha256()
    package_versions = tuple(sorted(packages))
    package_names = {canonicalize_name(name) for name, _ in package_versions}
    plugin_data: list[dict[str, str]] = []
    for group in ("fromager.hooks", "fromager.project_overrides"):
        for entry_point in importlib.metadata.entry_points(group=group):
            if (
                group == "fromager.project_overrides"
                and canonicalize_name(entry_point.name) not in package_names
            ):
                continue
            distribution = entry_point.dist
            plugin_data.append(
                {
                    "distribution": distribution.name if distribution else "",
                    "group": group,
                    "name": entry_point.name,
                    "value": entry_point.value,
                    "version": distribution.version if distribution else "",
                }
            )
    configuration = {
        "plugins": sorted(
            plugin_data,
            key=lambda value: (
                value["group"],
                value["name"],
                value["distribution"],
                value["version"],
                value["value"],
            ),
        ),
        "settings": ctx.settings.configuration_data(package_names),
    }
    settings_data = json.dumps(
        configuration,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest.update(settings_data.encode("utf-8"))

    patches_dir = ctx.settings.patches_dir.resolve()
    patches: set[pathlib.Path] = set()
    for name, version in package_versions:
        patches.update(ctx.package_build_info(name).get_patches(Version(version)))
    for patch in sorted(patches):
        patch = patch.resolve()
        digest.update(patch.relative_to(patches_dir).as_posix().encode("utf-8"))
        digest.update(_sha256(patch).encode("ascii"))
    return digest.hexdigest()


def _fromager_version() -> str:
    try:
        return importlib.metadata.version("fromager")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _artifact_record(root: pathlib.Path, filename: pathlib.Path) -> PrefetchArtifact:
    relative = filename.resolve().relative_to(root).as_posix()
    return PrefetchArtifact(
        path=relative,
        sha256=_sha256(filename),
        size=filename.stat().st_size,
    )


def _copy_artifact(
    root: pathlib.Path,
    source: pathlib.Path,
    relative_destination: pathlib.Path,
) -> PrefetchArtifact:
    destination = root / relative_destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = destination.parent.resolve()
    if not resolved_parent.is_relative_to(root):
        raise ValueError(f"prefetch destination escapes bundle root: {destination}")
    destination = resolved_parent / destination.name
    if destination.is_symlink():
        raise ValueError(f"prefetch destination is a symlink: {destination}")
    if source.resolve() == destination.resolve():
        return _artifact_record(root, destination)

    digest = hashlib.sha256()
    size = 0
    temporary_path: pathlib.Path | None = None
    try:
        with (
            source.open("rb") as source_file,
            tempfile.NamedTemporaryFile(
                dir=resolved_parent,
                prefix=f".{destination.name}.",
                delete=False,
            ) as temporary_file,
        ):
            temporary_path = pathlib.Path(temporary_file.name)
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                temporary_file.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        shutil.copystat(source, temporary_path, follow_symlinks=False)
        temporary_path.replace(destination)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise

    return PrefetchArtifact(
        path=destination.relative_to(root).as_posix(),
        sha256=digest.hexdigest(),
        size=size,
    )


def _write_manifest(root: pathlib.Path, manifest: PrefetchManifest) -> None:
    destination = root / MANIFEST_FILENAME
    if destination.is_symlink():
        raise ValueError(f"prefetch manifest is a symlink: {destination}")
    temporary_path: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=root,
            prefix=f".{MANIFEST_FILENAME}.",
            delete=False,
        ) as temporary_file:
            temporary_path = pathlib.Path(temporary_file.name)
            temporary_file.write(manifest.model_dump_json(indent=2) + "\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        temporary_path.replace(destination)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _load_build_order(filename: pathlib.Path) -> list[dict[str, typing.Any]]:
    try:
        value = json.loads(filename.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise ValueError(f"could not read build order {filename}: {err}") from err
    if not isinstance(value, list) or not all(
        isinstance(entry, dict) for entry in value
    ):
        raise ValueError(f"build order {filename} is not a list of objects")
    return typing.cast(list[dict[str, typing.Any]], value)


def _find_built_sdist(
    ctx: context.WorkContext, req: Requirement, version: str
) -> pathlib.Path | None:
    source = finders.find_sdist(ctx, ctx.sdists_builds, req, version)
    if source is not None:
        return source

    expected_name = canonicalize_name(req.name)
    expected_version = Version(version)
    for candidate in sorted(ctx.sdists_builds.glob("*")):
        try:
            name, candidate_version = parse_sdist_filename(candidate.name)
        except InvalidSdistFilename:
            continue
        if name == expected_name and candidate_version == expected_version:
            return candidate
    return None


def _source_workspace(
    ctx: context.WorkContext, source_root: str, workspace: str
) -> tuple[pathlib.Path, pathlib.Path]:
    source_root_path = (ctx.work_dir / pathlib.PurePosixPath(source_root)).resolve()
    workspace_path = (ctx.work_dir / pathlib.PurePosixPath(workspace)).resolve()
    if not workspace_path.is_relative_to(ctx.work_dir):
        raise ValueError(
            f"prepared source workspace escapes work directory: {workspace}"
        )
    if not source_root_path.is_relative_to(workspace_path):
        raise ValueError(f"prepared source root escapes work directory: {source_root}")
    if not source_root_path.is_dir():
        raise FileNotFoundError(
            f"prepared source workspace is missing: {source_root_path}"
        )
    return workspace_path, source_root_path


def _is_generated_source_entry(
    package_dir: pathlib.Path, source_root: pathlib.Path, path: pathlib.Path
) -> bool:
    if (
        path.parent == package_dir
        and path != source_root
        and (
            path.name.startswith("build-")
            or path.name in _GENERATED_SOURCE_FILES
            or path.suffix == ".log"
        )
    ):
        return True

    try:
        relative_path = path.relative_to(source_root)
    except ValueError:
        return False

    current_path = source_root
    for part in relative_path.parts:
        current_path /= part
        if part.endswith(".egg-info") or current_path.suffix in {".pyc", ".pyo"}:
            return True
        if part in _GENERATED_SOURCE_DIRECTORIES and current_path.is_dir():
            return True
    return False


def _write_prepared_source_archive(
    *,
    root: pathlib.Path,
    ctx: context.WorkContext,
    source_root: str,
    workspace: str,
    filename: str,
) -> pathlib.Path:
    package_dir, source_root_path = _source_workspace(ctx, source_root, workspace)

    destination_dir = root / "sdists"
    destination_dir.mkdir(parents=True, exist_ok=True)
    archive_filename = (
        f"{filename[:-4]}.tar.gz" if filename.endswith(".zip") else filename
    )
    destination = destination_dir / archive_filename
    if destination.is_symlink():
        raise ValueError(f"prefetch destination is a symlink: {destination}")
    temporary_path: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination_dir,
            prefix=f".{destination.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = pathlib.Path(temporary_file.name)
        with tarfile.open(temporary_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            tarballs.tar_reproducible(
                tar=archive,
                basedir=package_dir,
                prefix=package_dir,
                exclude_vcs=True,
                include_basedir=False,
                exclude=lambda path: _is_generated_source_entry(
                    package_dir, source_root_path, path
                ),
            )
        temporary_path.replace(destination)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return destination


def export_prefetch_bundle(
    ctx: context.WorkContext,
    destination_dir: pathlib.Path,
) -> PrefetchBundle:
    """Export bootstrap outputs as a self-contained prefetch bundle.

    Args:
        ctx: Completed bootstrap work context.
        destination_dir: Directory to populate with the bundle.

    Returns:
        The validated bundle.
    """
    root = destination_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)

    build_order_source = ctx.work_dir / "build-order.json"
    graph_source = ctx.graph_file
    build_order = _load_build_order(build_order_source)

    graph = _copy_artifact(root, graph_source, pathlib.Path("graph.json"))
    build_order_artifact = _copy_artifact(
        root, build_order_source, pathlib.Path("build-order.json")
    )

    constraints_source = ctx.work_dir / "constraints.txt"
    constraints = (
        _copy_artifact(root, constraints_source, pathlib.Path("constraints.txt"))
        if constraints_source.is_file()
        else None
    )
    merged_constraints_source = ctx.merged_constraints
    merged_constraints = (
        _copy_artifact(
            root,
            merged_constraints_source,
            pathlib.Path("merged-constraints.txt"),
        )
        if merged_constraints_source.is_file()
        else None
    )

    packages: list[PrefetchPackage] = []
    required_wheels: set[tuple[str, str]] = set()
    for entry in build_order:
        try:
            dist = str(entry["dist"])
            version = str(entry["version"])
            prebuilt = bool(entry["prebuilt"])
            source_url = str(entry["source_url"])
            raw_build_requirements = entry["build_requirements"]
        except KeyError as err:
            raise ValueError(f"build-order entry is missing {err.args[0]!r}") from err
        if not isinstance(raw_build_requirements, list) or not all(
            isinstance(requirement, str) for requirement in raw_build_requirements
        ):
            raise ValueError(f"invalid build requirements for {dist}=={version}")
        build_requirements = tuple(sorted(set(raw_build_requirements)))

        req = Requirement(f"{dist}=={version}")
        source: pathlib.Path | None
        if prebuilt:
            expected_source = ctx.wheels_prebuilt / downloads.extract_filename_from_url(
                source_url
            )
            source = expected_source if expected_source.is_file() else None
            if source is None:
                source = finders.find_wheel(ctx.wheels_prebuilt, req, version)
            subdir = pathlib.Path("prebuilt")
        else:
            source = _find_built_sdist(ctx, req, version)
            subdir = pathlib.Path("sdists")
        if source is None:
            kind = "prebuilt wheel" if prebuilt else "patched sdist"
            raise FileNotFoundError(f"could not find {kind} for {req}")

        node_key = f"{canonicalize_name(dist)}=={version}"
        if node_key not in ctx.dependency_graph.nodes:
            raise ValueError(f"build order references missing graph node {node_key}")
        required_wheels.update(
            _exact_requirement_coordinate(requirement)
            for requirement in build_requirements
        )

        if not prebuilt:
            prepared_source_root = entry.get("prepared_source_root")
            prepared_source_workspace = entry.get("prepared_source_workspace")
            if not isinstance(prepared_source_root, str) or not isinstance(
                prepared_source_workspace, str
            ):
                raise ValueError(
                    f"build-order entry has no prepared source workspace for {req}"
                )
            prepared_source = _write_prepared_source_archive(
                root=root,
                ctx=ctx,
                source_root=prepared_source_root,
                workspace=prepared_source_workspace,
                filename=source.name,
            )
            artifact = _artifact_record(root, prepared_source)
        else:
            artifact = _copy_artifact(root, source, subdir / source.name)
        packages.append(
            PrefetchPackage(
                dist=dist,
                version=version,
                prebuilt=prebuilt,
                artifact=artifact,
                build_requirements=build_requirements,
            )
        )

    wheel_records: dict[str, PrefetchWheel] = {}
    for dist, version in sorted(required_wheels):
        req = Requirement(f"{dist}=={version}")
        build_tag = ctx.package_build_info(req).build_tag(Version(version))
        source = finders.find_exact_wheel(
            (ctx.wheels_downloads, ctx.wheels_prebuilt),
            req,
            version,
            build_tag,
        )
        if source is None:
            raise FileNotFoundError(
                f"could not find build-environment wheel for {dist}=={version}"
            )
        wheel_subdir = pathlib.Path(
            "prebuilt" if source.parent == ctx.wheels_prebuilt else "wheels"
        )
        artifact = _copy_artifact(root, source, wheel_subdir / source.name)
        wheel_records[artifact.path] = PrefetchWheel(
            dist=dist,
            version=version,
            artifact=artifact,
        )

    manifest = PrefetchManifest(
        fromager_version=_fromager_version(),
        python_version=platform.python_version(),
        python_implementation=sys.implementation.name,
        platform=sysconfig.get_platform(),
        variant=ctx.variant,
        settings_fingerprint=configuration_fingerprint(
            ctx, ((package.dist, package.version) for package in packages)
        ),
        graph=graph,
        build_order=build_order_artifact,
        constraints=constraints,
        merged_constraints=merged_constraints,
        packages=tuple(packages),
        wheels=tuple(wheel_records[path] for path in sorted(wheel_records)),
    )
    _write_manifest(root, manifest)
    return load_prefetch_bundle(root, expected_variant=ctx.variant)


def load_prefetch_bundle(
    directory: pathlib.Path,
    *,
    expected_variant: str | None = None,
    verify_environment: bool = True,
) -> PrefetchBundle:
    """Load and verify a prefetch bundle.

    Args:
        directory: Bundle directory containing ``manifest.json``.
        expected_variant: Required variant, when supplied.
        verify_environment: Verify the current Python and platform.

    Returns:
        The verified bundle.
    """
    root = directory.resolve()
    manifest_path = root / MANIFEST_FILENAME
    try:
        manifest = PrefetchManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, pydantic.ValidationError) as err:
        raise ValueError(
            f"could not load prefetch manifest {manifest_path}: {err}"
        ) from err

    if expected_variant is not None and manifest.variant != expected_variant:
        raise ValueError(
            f"prefetch variant {manifest.variant!r} does not match "
            f"build variant {expected_variant!r}"
        )

    if verify_environment:
        expected_environment = {
            "fromager_version": _fromager_version(),
            "python_version": platform.python_version(),
            "python_implementation": sys.implementation.name,
            "platform": sysconfig.get_platform(),
        }
        for field, expected in expected_environment.items():
            actual = getattr(manifest, field)
            if actual != expected:
                raise ValueError(
                    f"prefetch {field} {actual!r} does not match "
                    f"build environment {expected!r}"
                )

    bundle = PrefetchBundle(root=root, manifest=manifest)
    artifacts: list[PrefetchArtifact] = [manifest.graph, manifest.build_order]
    if manifest.constraints is not None:
        artifacts.append(manifest.constraints)
    if manifest.merged_constraints is not None:
        artifacts.append(manifest.merged_constraints)
    artifacts.extend(package.artifact for package in manifest.packages)
    artifacts.extend(wheel.artifact for wheel in manifest.wheels)

    for artifact in artifacts:
        bundle.verify_artifact(artifact)

    return bundle
