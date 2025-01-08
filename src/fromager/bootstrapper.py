from __future__ import annotations

import json
import logging
import operator
import pathlib
import shutil
import typing
import zipfile
from urllib.parse import urlparse

from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version

from . import (
    build_environment,
    dependencies,
    finders,
    progress,
    resolver,
    server,
    sources,
    wheels,
)
from .dependency_graph import DependencyGraph
from .requirements_file import RequirementType, SourceType

if typing.TYPE_CHECKING:
    from . import context

logger = logging.getLogger(__name__)


class Bootstrapper:
    def __init__(
        self,
        ctx: context.WorkContext,
        progressbar: progress.Progressbar | None = None,
        prev_graph: DependencyGraph | None = None,
        cache_wheel_server_url: str | None = None,
    ) -> None:
        self.ctx = ctx
        self.progressbar = progressbar or progress.Progressbar(None)
        self.prev_graph = prev_graph
        self.cache_wheel_server_url = cache_wheel_server_url or ctx.wheel_server_url
        self.why: list[tuple[RequirementType, Requirement, Version]] = []
        # Push items onto the stack as we start to resolve their
        # dependencies so at the end we have a list of items that need to
        # be built in order.
        self._build_stack: list[typing.Any] = []
        self._build_requirements: set[tuple[NormalizedName, str]] = set()

        # Track requirements we've seen before so we don't resolve the
        # same dependencies over and over and so we can break cycles in
        # the dependency list. The key is the requirements spec, rather
        # than the package, in case we do have multiple rules for the same
        # package.
        self._seen_requirements: set[tuple[NormalizedName, tuple[str, ...], str]] = (
            set()
        )

        self._build_order_filename = self.ctx.work_dir / "build-order.json"

    def bootstrap(self, req: Requirement, req_type: RequirementType) -> Version:
        constraint = self.ctx.constraints.get_constraint(req.name)
        if constraint:
            logger.info(
                f"{req.name}: incoming requirement {req} matches constraint {constraint}. Will apply both."
            )

        pbi = self.ctx.package_build_info(req)
        if pbi.pre_built:
            wheel_url, resolved_version = self._resolve_prebuilt_with_history(
                req=req,
                req_type=req_type,
            )
            source_url = wheel_url
        else:
            source_url, resolved_version = self._resolve_source_with_history(
                req=req,
                req_type=req_type,
            )

        self._add_to_graph(req, req_type, resolved_version, source_url)

        # Avoid cyclic dependencies and redundant processing.
        if self._has_been_seen(req, resolved_version):
            logger.debug(
                f"{req.name}: redundant {req_type} dependency {req} ({resolved_version}) for {self._explain}"
            )
            return resolved_version
        self._mark_as_seen(req, resolved_version)

        logger.info(
            f"{req.name}: new {req_type} dependency {req} resolves to {resolved_version}"
        )

        # Build the dependency chain up to the point of this new
        # requirement using a new list so we can avoid modifying the list
        # we're given.
        self.why.append((req_type, req, resolved_version))

        # for cleanup
        build_env = None
        sdist_root_dir = None
        if pbi.pre_built:
            wheel_filename, unpack_dir = self._download_prebuilt(
                req=req,
                req_type=req_type,
                resolved_version=resolved_version,
                wheel_url=source_url,
            )
            # Remember that this is a prebuilt wheel, and where we got it.
            source_url_type = str(SourceType.PREBUILT)
        else:
            unpacked_cached_wheel, cached_wheel_filename = (
                self._download_wheel_from_cache(req, resolved_version)
            )
            source_url_type = sources.get_source_type(self.ctx, req)

            if not unpacked_cached_wheel:
                source_filename = sources.download_source(
                    ctx=self.ctx,
                    req=req,
                    version=resolved_version,
                    download_url=source_url,
                )
                sdist_root_dir = sources.prepare_source(
                    ctx=self.ctx,
                    req=req,
                    source_filename=source_filename,
                    version=resolved_version,
                )
                unpack_dir = sdist_root_dir.parent
            else:
                sdist_root_dir = unpacked_cached_wheel
                unpack_dir = unpacked_cached_wheel.parent

            # need to call this function irrespective of whether we had the wheel cached
            # so that the build dependencies can be bootstrapped
            build_dependencies = self._prepare_build_dependencies(req, sdist_root_dir)

            # skip building even if it is a non-fromager built wheel
            if not cached_wheel_filename:
                wheel_filename, build_env = self._build(
                    req, resolved_version, sdist_root_dir, build_dependencies
                )
            else:
                wheel_filename = cached_wheel_filename

        self._add_to_build_order(
            req=req,
            version=resolved_version,
            source_url=source_url,
            source_url_type=source_url_type,
            prebuilt=pbi.pre_built,
            constraint=constraint,
        )

        # Process installation dependencies for all wheels.
        install_dependencies = dependencies.get_install_dependencies_of_wheel(
            req, wheel_filename, unpack_dir
        )
        self.progressbar.update_total(len(install_dependencies))
        for dep in self._sort_requirements(install_dependencies):
            try:
                self.bootstrap(dep, RequirementType.INSTALL)
            except Exception as err:
                raise ValueError(f"could not handle {self._explain}") from err
            self.progressbar.update()

        # we are done processing this req, so lets remove it from the why chain
        self.why.pop()
        self._cleanup(req, sdist_root_dir, build_env)
        return resolved_version

    @property
    def _explain(self) -> str:
        """Return message formatting current version of why stack."""
        return " for ".join(
            f"{req_type} dependency {req} ({resolved_version})"
            for req_type, req, resolved_version in reversed(self.why)
        )

    def _build(
        self,
        req: Requirement,
        resolved_version: Version,
        sdist_root_dir: pathlib.Path,
        build_dependencies: set[Requirement],
    ) -> tuple[pathlib.Path, build_environment.BuildEnvironment]:
        build_env = build_environment.BuildEnvironment(
            self.ctx,
            sdist_root_dir.parent,
            build_dependencies,
        )
        try:
            find_sdist_result = finders.find_sdist(
                self.ctx, self.ctx.sdists_builds, req, str(resolved_version)
            )
            if not find_sdist_result:
                sources.build_sdist(
                    ctx=self.ctx,
                    req=req,
                    version=resolved_version,
                    sdist_root_dir=sdist_root_dir,
                    build_env=build_env,
                )
            else:
                logger.info(
                    f"{req.name} have sdist version {resolved_version}: {find_sdist_result}"
                )
        except Exception as err:
            logger.warning(f"{req.name}: failed to build source distribution: {err}")

        logger.info(f"{req.name}: starting build of {self._explain}")
        built_filename = wheels.build_wheel(
            ctx=self.ctx,
            req=req,
            sdist_root_dir=sdist_root_dir,
            version=resolved_version,
            build_env=build_env,
        )
        server.update_wheel_mirror(self.ctx)
        # When we update the mirror, the built file moves to the
        # downloads directory.
        wheel_filename = self.ctx.wheels_downloads / built_filename.name
        logger.info(
            f"{req.name}: built wheel for version {resolved_version}: {wheel_filename}"
        )
        return wheel_filename, build_env

    def _prepare_build_dependencies(
        self, req: Requirement, sdist_root_dir: pathlib.Path
    ) -> set[Requirement]:
        build_system_dependencies = dependencies.get_build_system_dependencies(
            ctx=self.ctx, req=req, sdist_root_dir=sdist_root_dir
        )
        self._handle_build_requirements(
            RequirementType.BUILD_SYSTEM,
            build_system_dependencies,
        )

        build_backend_dependencies = dependencies.get_build_backend_dependencies(
            ctx=self.ctx, req=req, sdist_root_dir=sdist_root_dir
        )
        self._handle_build_requirements(
            RequirementType.BUILD_BACKEND,
            build_backend_dependencies,
        )

        build_sdist_dependencies = dependencies.get_build_sdist_dependencies(
            ctx=self.ctx, req=req, sdist_root_dir=sdist_root_dir
        )
        self._handle_build_requirements(
            RequirementType.BUILD_SDIST,
            build_sdist_dependencies,
        )

        return (
            build_system_dependencies
            | build_backend_dependencies
            | build_sdist_dependencies
        )

    def _handle_build_requirements(
        self, build_type: RequirementType, build_dependencies: set[Requirement]
    ) -> None:
        self.progressbar.update_total(len(build_dependencies))

        for dep in self._sort_requirements(build_dependencies):
            try:
                resolved = self.bootstrap(req=dep, req_type=build_type)
            except Exception as err:
                raise ValueError(f"could not handle {self._explain}") from err
            # We may need these dependencies installed in order to run build hooks
            # Example: frozenlist build-system.requires includes expandvars because
            # it is used by the packaging/pep517_backend/ build backend
            build_environment.maybe_install(self.ctx, dep, build_type, str(resolved))
            self.progressbar.update()

    def _download_prebuilt(
        self,
        req: Requirement,
        req_type: RequirementType,
        resolved_version: Version,
        wheel_url: str,
    ) -> tuple[pathlib.Path, pathlib.Path]:
        logger.info(f"{req.name}: {req_type} requirement {req} uses a pre-built wheel")

        wheel_filename = wheels.download_wheel(req, wheel_url, self.ctx.wheels_prebuilt)

        # Add the wheel to the mirror so it is available to anything
        # that needs to install it. We leave a copy in the prebuilt
        # directory to make it easy to remove the wheel from the
        # downloads directory before uploading to a proper package
        # index.
        dest_name = self.ctx.wheels_downloads / wheel_filename.name
        if not dest_name.exists():
            logger.info(f"{req.name}: updating temporary mirror with pre-built wheel")
            shutil.copy(wheel_filename, dest_name)
            server.update_wheel_mirror(self.ctx)
        unpack_dir = self._create_unpack_dir(req, resolved_version)
        return (wheel_filename, unpack_dir)

    def _download_wheel_from_cache(
        self, req: Requirement, resolved_version: Version
    ) -> tuple[pathlib.Path | None, pathlib.Path | None]:
        if not self.cache_wheel_server_url:
            return None, None
        logger.info(
            f"{req.name}: checking if wheel was already uploaded to {self.cache_wheel_server_url}"
        )
        try:
            wheel_url, _ = resolver.resolve(
                ctx=self.ctx,
                req=Requirement(f"{req.name}=={resolved_version}"),
                sdist_server_url=self.cache_wheel_server_url,
                include_sdists=False,
                include_wheels=True,
            )
            wheelfile_name = pathlib.Path(urlparse(wheel_url).path)
            pbi = self.ctx.package_build_info(req)
            expected_build_tag = pbi.build_tag(resolved_version)
            dist_name, dist_version, build_tag, _ = wheels.extract_info_from_wheel_file(
                req, wheelfile_name
            )
            if expected_build_tag and expected_build_tag != build_tag:
                logger.info(
                    f"{req.name}: found wheel for {resolved_version} in cache but build tag does not match. Got {build_tag} but expected {expected_build_tag}"
                )
                return None, None

            cached_wheel = wheels.download_wheel(
                req=req, wheel_url=wheel_url, output_directory=self.ctx.wheels_downloads
            )
            if self.cache_wheel_server_url != self.ctx.wheel_server_url:
                # Only update the local server if we actually downloaded
                # something from a different server.
                server.update_wheel_mirror(self.ctx)
            logger.info(f"{req.name}: found built wheel on cache server")
            unpack_dir = self._create_unpack_dir(req, resolved_version)
            dist_filename = f"{dist_name}-{dist_version}"
            metadata_dir = pathlib.Path(f"{dist_filename}.dist-info")
            try:
                archive = zipfile.ZipFile(cached_wheel)
                for filename in [
                    dependencies.BUILD_BACKEND_REQ_FILE_NAME,
                    dependencies.BUILD_SDIST_REQ_FILE_NAME,
                    dependencies.BUILD_SYSTEM_REQ_FILE_NAME,
                ]:
                    zipinfo = archive.getinfo(
                        str(
                            metadata_dir
                            / f"{wheels.FROMAGER_BUILD_REQ_PREFIX}-{filename}"
                        )
                    )
                    zipinfo.filename = filename
                    archive.extract(zipinfo, unpack_dir)

                logger.info(f"{req.name}: extracted build requirements from wheel")
                return unpack_dir / metadata_dir, cached_wheel
            except Exception:
                # implies that the wheel server hosted non-fromager built wheels
                logger.info(
                    f"{req.name}: could not extract build requirements from wheel"
                )
                shutil.rmtree(unpack_dir)
                return None, cached_wheel
        except Exception:
            logger.info(
                f"{req.name}: did not find wheel for {resolved_version} in {self.cache_wheel_server_url}"
            )
            return None, None

    def _resolve_source_with_history(
        self,
        req: Requirement,
        req_type: RequirementType,
    ) -> tuple[str, Version]:
        cached_resolution = self._resolve_from_graph(
            req=req,
            req_type=req_type,
            pre_built=False,
        )
        if cached_resolution:
            source_url, resolved_version = cached_resolution
            logger.debug(
                f"{req.name}: resolved from previous bootstrap to {resolved_version}"
            )
        else:
            source_url, resolved_version = sources.resolve_source(
                ctx=self.ctx,
                req=req,
                sdist_server_url=resolver.PYPI_SERVER_URL,
                req_type=req_type,
            )
        return (source_url, resolved_version)

    def _resolve_prebuilt_with_history(
        self,
        req: Requirement,
        req_type: RequirementType,
    ) -> tuple[str, Version]:
        cached_resolution = self._resolve_from_graph(
            req=req,
            req_type=req_type,
            pre_built=True,
        )

        if cached_resolution:
            wheel_url, resolved_version = cached_resolution
            logger.debug(
                f"{req.name}: resolved from previous bootstrap to {resolved_version}"
            )
        else:
            servers = wheels.get_wheel_server_urls(self.ctx, req)
            wheel_url, resolved_version = wheels.resolve_prebuilt_wheel(
                ctx=self.ctx, req=req, wheel_server_urls=servers, req_type=req_type
            )
        return (wheel_url, resolved_version)

    def _resolve_from_graph(
        self,
        req: Requirement,
        req_type: RequirementType,
        pre_built: bool,
    ) -> tuple[str, Version] | None:
        _, parent_req, _ = self.why[-1] if self.why else (None, None, None)

        # we have already resolved top level reqs before bootstrapping
        # so they should already be in the root node
        if req_type == RequirementType.TOP_LEVEL:
            for edge in self.ctx.dependency_graph.get_root_node().get_outgoing_edges(
                req.name, RequirementType.TOP_LEVEL
            ):
                if edge.req == req:
                    return (
                        edge.destination_node.download_url,
                        edge.destination_node.version,
                    )
            # this should never happen since we already resolved top level reqs and their
            # resolution should be in the root nodes
            raise ValueError(
                f"{req.name}: {req} appears as a toplevel requirement but it's resolution does not exist in the root node of the graph"
            )

        if not self.prev_graph:
            return None

        seen_version: set[str] = set()

        # first perform resolution using the top level reqs before looking at history
        possible_versions_in_top_level: list[tuple[str, Version]] = []
        for (
            top_level_edge
        ) in self.ctx.dependency_graph.get_root_node().get_outgoing_edges(
            req.name, RequirementType.TOP_LEVEL
        ):
            possible_versions_in_top_level.append(
                (
                    top_level_edge.destination_node.download_url,
                    top_level_edge.destination_node.version,
                )
            )
            seen_version.add(str(top_level_edge.destination_node.version))

        resolver_result = self._resolve_from_version_source(
            possible_versions_in_top_level, req
        )
        if resolver_result:
            return resolver_result

        # only if there is nothing in top level reqs, resolve using history
        possible_versions_from_graph: list[tuple[str, Version]] = []
        # check all nodes which have the same parent name irrespective of the parent's version
        for parent_node in self.prev_graph.get_nodes_by_name(
            parent_req.name if parent_req else None
        ):
            # if the edge matches the current req and type then it is a possible candidate
            # filtering on type might not be necessary, but we are being safe here. This will
            # for sure ensure that bootstrap takes the same route as it did in the previous one.
            # If we don't filter by type then it might pick up a different version from a different
            # type that should have appeared much later in the resolution process.
            for edge in parent_node.get_outgoing_edges(req.name, req_type):
                if (
                    edge.destination_node.pre_built == pre_built
                    and str(edge.destination_node.version) not in seen_version
                ):
                    possible_versions_from_graph.append(
                        (
                            edge.destination_node.download_url,
                            edge.destination_node.version,
                        )
                    )
                    seen_version.add(str(edge.destination_node.version))

        return self._resolve_from_version_source(possible_versions_from_graph, req)

    def _resolve_from_version_source(
        self,
        version_source: list[tuple[str, Version]],
        req: Requirement,
    ) -> tuple[str, Version] | None:
        if not version_source:
            return None
        try:
            # no need to pass req type to enable caching since we are already using the graph as our cache
            provider = resolver.GenericProvider(
                version_source=lambda x, y, z: version_source,
                constraints=self.ctx.constraints,
            )
            return resolver.resolve_from_provider(provider, req)
        except Exception as err:
            logger.debug(
                f"{req.name}: could not resolve {req} from {version_source}: {err}"
            )
            return None

    def _create_unpack_dir(self, req: Requirement, resolved_version: Version):
        unpack_dir = self.ctx.work_dir / f"{req.name}-{resolved_version}"
        if not unpack_dir.exists():
            unpack_dir.mkdir()
        return unpack_dir

    def _cleanup(
        self,
        req: Requirement,
        sdist_root_dir: pathlib.Path | None,
        build_env: build_environment.BuildEnvironment | None,
    ) -> None:
        if not self.ctx.cleanup:
            return

        # Cleanup the source tree and build environment, leaving any other
        # artifacts that were created.
        if sdist_root_dir and sdist_root_dir.exists():
            logger.debug(f"{req.name}: cleaning up source tree {sdist_root_dir}")
            shutil.rmtree(sdist_root_dir)
            logger.debug(f"{req.name}: cleaned up source tree {sdist_root_dir}")
        if build_env:
            logger.debug(f"{req.name}: cleaning up build environment {build_env.path}")
            shutil.rmtree(build_env.path)
            logger.debug(f"{req.name}: cleaned up build environment {build_env.path}")

    def _add_to_graph(
        self,
        req: Requirement,
        req_type: RequirementType,
        req_version: Version,
        download_url: str,
    ) -> None:
        if req_type == RequirementType.TOP_LEVEL:
            return

        _, parent_req, parent_version = self.why[-1] if self.why else (None, None, None)
        pbi = self.ctx.package_build_info(req)
        # Update the dependency graph after we determine that this requirement is
        # useful but before we determine if it is redundant so that we capture all
        # edges to use for building a valid constraints file.
        self.ctx.dependency_graph.add_dependency(
            parent_name=canonicalize_name(parent_req.name) if parent_req else None,
            parent_version=parent_version,
            req_type=req_type,
            req=req,
            req_version=req_version,
            download_url=download_url,
            pre_built=pbi.pre_built,
        )
        self.ctx.write_to_graph_to_file()

    def _sort_requirements(
        self,
        requirements: typing.Iterable[Requirement],
    ) -> typing.Iterable[Requirement]:
        return sorted(requirements, key=operator.attrgetter("name"))

    def _resolved_key(
        self, req: Requirement, version: Version
    ) -> tuple[NormalizedName, tuple[str, ...], str]:
        return (canonicalize_name(req.name), tuple(sorted(req.extras)), str(version))

    def _mark_as_seen(self, req: Requirement, version: Version) -> None:
        key = self._resolved_key(req, version)
        logger.debug(f"{req.name}: remembering seen sdist {key}")
        self._seen_requirements.add(key)

    def _has_been_seen(self, req: Requirement, version: Version) -> bool:
        return self._resolved_key(req, version) in self._seen_requirements

    def _add_to_build_order(
        self,
        req: Requirement,
        version: Version,
        source_url: str,
        source_url_type: str,
        prebuilt: bool = False,
        constraint: Requirement | None = None,
    ) -> None:
        # We only care if this version of this package has been built,
        # and don't want to trigger building it twice. The "extras"
        # value, included in the _resolved_key() output, can confuse
        # that so we ignore itand build our own key using just the
        # name and version.
        key = (canonicalize_name(req.name), str(version))
        if key in self._build_requirements:
            return
        logger.info(f"{req.name}: adding {key} to build order")
        self._build_requirements.add(key)
        info = {
            "req": str(req),
            "constraint": str(constraint) if constraint else "",
            "dist": canonicalize_name(req.name),
            "version": str(version),
            "prebuilt": prebuilt,
            "source_url": source_url,
            "source_url_type": source_url_type,
        }
        self._build_stack.append(info)
        with open(self._build_order_filename, "w") as f:
            # Set default=str because the why value includes
            # Requirement and Version instances that can't be
            # converted to JSON without help.
            json.dump(self._build_stack, f, indent=2, default=str)
