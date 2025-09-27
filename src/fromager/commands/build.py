import concurrent.futures
import dataclasses
import datetime
import json
import logging
import pathlib
import sys
import threading
import typing
from urllib.parse import urlparse

import click
import rich
import rich.box
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version
from rich.table import Table
from rich.text import Text

from fromager import (
    build_environment,
    clickext,
    context,
    dependency_graph,
    hooks,
    metrics,
    overrides,
    progress,
    read,
    server,
    sources,
    wheels,
)

from .. import resolver
from ..log import VERBOSE_LOG_FMT, ThreadLogFilter, req_ctxvar_context

logger = logging.getLogger(__name__)

DependencyNodeList = list[dependency_graph.DependencyNode]


@dataclasses.dataclass(order=True, frozen=True)
class BuildSequenceEntry:
    # compare, hash, and sort by name and version
    name: str
    version: Version
    prebuilt: bool = dataclasses.field(compare=False)
    download_url: str = dataclasses.field(compare=False)
    wheel_filename: pathlib.Path = dataclasses.field(compare=False)
    skipped: bool = dataclasses.field(default=False, compare=False)

    @staticmethod
    def dict_factory(x):
        return {
            k: str(v) if isinstance(v, pathlib.Path | Version) else v for (k, v) in x
        }


@click.command()
@click.option(
    "--wheel-server-url",
    default="",
    type=str,
    help="URL for the wheel server for builds",
)
@click.argument("dist_name")
@click.argument("dist_version", type=clickext.PackageVersion())
@click.argument("sdist_server_url")
@click.pass_obj
def build(
    wkctx: context.WorkContext,
    wheel_server_url: str,
    dist_name: str,
    dist_version: Version,
    sdist_server_url: str,
) -> None:
    """Build a single version of a single wheel

    DIST_NAME is the name of a distribution

    DIST_VERSION is the version to process

    SDIST_SERVER_URL is the URL for a PyPI-compatible package index hosting sdists

    1. Downloads the source distribution.

    2. Unpacks it and prepares the source via patching, vendoring rust
       dependencies, etc.

    3. Prepares a build environment with the build dependencies.

    4. Builds the wheel.

    Refer to the 'step' commands for scripting these stages
    separately.

    """
    wkctx.wheel_server_url = wheel_server_url
    server.start_wheel_server(wkctx)
    req = Requirement(f"{dist_name}=={dist_version}")
    with req_ctxvar_context(req, dist_version):
        # We have to resolve the source here to get a
        # source_url. Other build modes use data computed from a
        # bootstrap job where that URL is saved in the build
        # instruction file passed to build-sequence or build-parallel.
        source_url, version = sources.resolve_source(
            ctx=wkctx,
            req=req,
            sdist_server_url=sdist_server_url,
        )
        entry = _build(
            wkctx=wkctx,
            resolved_version=version,
            req=req,
            source_download_url=source_url,
            force=True,
            cache_wheel_server_url=None,
        )
    print(entry.wheel_filename)


build._fromager_show_build_settings = True  # type: ignore


@click.command()
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="rebuild wheels even if they have already been built",
)
@click.option(
    "-c",
    "--cache-wheel-server-url",
    "cache_wheel_server_url",
    help="url to a wheel server from where fromager can check if it had already built the wheel",
)
@click.argument("build_order_file")
@click.pass_obj
def build_sequence(
    wkctx: context.WorkContext,
    build_order_file: str,
    force: bool,
    cache_wheel_server_url: str | None,
) -> None:
    """Build a sequence of wheels in order

    BUILD_ORDER_FILE is the build-order.json files to build

    SDIST_SERVER_URL is the URL for a PyPI-compatible package index hosting sdists

    Performs the equivalent of the 'build' command for each item in
    the build order file.

    """
    server.start_wheel_server(wkctx)

    if force:
        logger.info(
            "rebuilding all wheels even if they exist in "
            f"{wkctx.wheel_server_url=}, {cache_wheel_server_url=}"
        )
    else:
        logger.info(
            "skipping builds for versions of packages available at "
            f"{wkctx.wheel_server_url=}, {cache_wheel_server_url=}"
        )

    entries: list[BuildSequenceEntry] = []

    logger.info("reading build order from %s", build_order_file)
    with read.open_file_or_url(build_order_file) as f:
        for entry in progress.progress(json.load(f)):
            dist_name = entry["dist"]
            resolved_version = Version(entry["version"])
            source_download_url = entry["source_url"]

            # If we are building from git, use the requirement as specified so
            # we include the URL. Otherwise, create a fake requirement with the
            # name and version so we are explicitly building the expected
            # version.
            if entry["source_url_type"] == "git":
                req = Requirement(entry["req"])
            else:
                req = Requirement(f"{dist_name}=={resolved_version}")

            with req_ctxvar_context(req, resolved_version):
                logger.info("building %s", resolved_version)
                entry = _build(
                    wkctx=wkctx,
                    resolved_version=resolved_version,
                    req=req,
                    source_download_url=source_download_url,
                    force=force,
                    cache_wheel_server_url=cache_wheel_server_url,
                )
                if entry.prebuilt:
                    logger.info(
                        "downloaded prebuilt wheel %s", entry.wheel_filename.name
                    )
                elif entry.skipped:
                    logger.info(
                        "skipping building wheel since %s already exists",
                        entry.wheel_filename.name,
                    )
                else:
                    logger.info("built %s", entry.wheel_filename.name)

                entries.append(entry)

    metrics.summarize(wkctx, "Building")

    _summary(wkctx, entries)


build_sequence._fromager_show_build_settings = True  # type: ignore


def _summary(ctx: context.WorkContext, entries: list[BuildSequenceEntry]) -> None:
    output: list[typing.Any] = []
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    output.append(Text(f"Build sequence summary {now}\n"))

    built_entries = [e for e in entries if not e.skipped and not e.prebuilt]
    if built_entries:
        output.append(
            _create_table(
                built_entries,
                title="New builds",
                box=rich.box.MARKDOWN,
                title_justify="left",
            )
        )
    else:
        output.append(Text("No new builds\n"))

    prebuilt_entries = [e for e in entries if e.prebuilt]
    if prebuilt_entries:
        output.append(
            _create_table(
                prebuilt_entries,
                title="Prebuilt wheels",
                box=rich.box.MARKDOWN,
                title_justify="left",
            )
        )
    else:
        output.append(Text("No pre-built wheels\n"))

    skipped_entries = [e for e in entries if e.skipped and not e.prebuilt]
    if skipped_entries:
        output.append(
            _create_table(
                skipped_entries,
                title="Skipped existing builds",
                box=rich.box.MARKDOWN,
                title_justify="left",
            )
        )
    else:
        output.append(Text("No skipped builds\n"))

    console = rich.get_console()
    console.print(*output, sep="\n\n")

    with open(ctx.work_dir / "build-sequence-summary.md", "w", encoding="utf-8") as f:
        console = rich.console.Console(file=f, width=sys.maxsize)
        console.print(*output, sep="\n\n")

    with open(ctx.work_dir / "build-sequence-summary.json", "w", encoding="utf-8") as f:
        json.dump(
            [
                dataclasses.asdict(e, dict_factory=BuildSequenceEntry.dict_factory)
                for e in entries
            ],
            f,
        )


def _create_table(entries: list[BuildSequenceEntry], **table_kwargs) -> Table:
    table = Table(**table_kwargs)
    table.add_column("Name", justify="right", no_wrap=True)
    table.add_column("Version", no_wrap=True)
    table.add_column("Wheel", no_wrap=True)
    table.add_column("Source URL")

    platlib_count = 0

    for info in sorted(entries):
        tags = parse_wheel_filename(info.wheel_filename.name)[3]
        if any(t.platform != "any" or t.abi != "none" for t in tags):
            platlib_count += 1
        source_filename = urlparse(info.download_url).path.rsplit("/", 1)[-1]
        table.add_row(
            info.name,
            str(info.version),
            info.wheel_filename.name,
            # escape Rich markup
            rf"\[{source_filename}]({info.download_url})",
        )

    # summary
    table.add_section()
    table.add_row(
        f"total: {len(entries)}",
        None,
        f"platlib: {platlib_count}",
        None,
    )
    return table


def _build(
    wkctx: context.WorkContext,
    resolved_version: Version,
    req: Requirement,
    source_download_url: str,
    force: bool,
    cache_wheel_server_url: str | None,
) -> BuildSequenceEntry:
    """Handle one version of one wheel.

    Either:
    1. Reuse an existing wheel we have locally.
    2. Download a pre-built wheel.
    3. Build the wheel from source.
    """
    wheel_filename: pathlib.Path | None = None
    use_exiting_wheel: bool = False

    # Set up a log file for all of the details of the build for this one wheel.
    # We attach a handler to the root logger so that all messages are logged to
    # the file, and we add a filter to the handler so that only messages from
    # the current thread are logged for when we build in parallel.
    root_logger = logging.getLogger(None)
    module_name = overrides.pkgname_to_override_module(req.name)
    wheel_log = wkctx.logs_dir / f"{module_name}-{resolved_version}.log"
    file_handler = logging.FileHandler(filename=str(wheel_log))
    file_handler.setFormatter(logging.Formatter(VERBOSE_LOG_FMT))
    file_handler.addFilter(ThreadLogFilter(threading.current_thread().name))
    root_logger.addHandler(file_handler)

    logger.info("starting processing")
    pbi = wkctx.package_build_info(req)
    prebuilt = pbi.pre_built

    wheel_server_urls = wheels.get_wheel_server_urls(
        wkctx, req, cache_wheel_server_url=cache_wheel_server_url
    )

    # See if we can reuse an existing wheel.
    if not force:
        wheel_filename = _is_wheel_built(
            wkctx,
            req.name,
            resolved_version,
            wheel_server_urls,
        )
        if wheel_filename:
            logger.info("using existing wheel from %s", wheel_filename)
            use_exiting_wheel = True

    # Handle prebuilt wheels.
    if prebuilt:
        if not wheel_filename:
            logger.info("downloading prebuilt wheel")
            wheel_filename = wheels.download_wheel(
                req=req,
                wheel_url=source_download_url,
                output_directory=wkctx.wheels_build,
            )
        else:
            # already downloaded prebuilt wheel
            use_exiting_wheel = True

        # Run hooks for prebuilt wheels. At this point wheel_filename should
        # be set either from _is_wheel_built() or download_wheel().
        hooks.run_prebuilt_wheel_hooks(
            ctx=wkctx,
            req=req,
            dist_name=req.name,
            dist_version=str(resolved_version),
            wheel_filename=wheel_filename,
        )

    # If we get here and still don't have a wheel filename, then we need to
    # build the wheel.
    if not wheel_filename:
        source_filename = sources.download_source(
            ctx=wkctx,
            req=req,
            version=resolved_version,
            download_url=source_download_url,
        )
        logger.debug(
            "saved sdist of version %s from %s to %s",
            resolved_version,
            source_download_url,
            source_filename,
        )

        # Prepare source
        source_root_dir = sources.prepare_source(
            ctx=wkctx,
            req=req,
            source_filename=source_filename,
            version=resolved_version,
        )

        # Build environment
        build_env = build_environment.prepare_build_environment(
            ctx=wkctx, req=req, sdist_root_dir=source_root_dir
        )

        # Make a new source distribution, in case we patched the code.
        sdist_filename = sources.build_sdist(
            ctx=wkctx,
            req=req,
            version=resolved_version,
            sdist_root_dir=source_root_dir,
            build_env=build_env,
        )

        # Build
        wheel_filename = wheels.build_wheel(
            ctx=wkctx,
            req=req,
            sdist_root_dir=source_root_dir,
            version=resolved_version,
            build_env=build_env,
        )

        hooks.run_post_build_hooks(
            ctx=wkctx,
            req=req,
            dist_name=canonicalize_name(req.name),
            dist_version=str(resolved_version),
            sdist_filename=sdist_filename,
            wheel_filename=wheel_filename,
        )

        wkctx.clean_build_dirs(source_root_dir, build_env)

    root_logger.removeHandler(file_handler)
    file_handler.close()

    server.update_wheel_mirror(wkctx)

    # After we update the wheel mirror, the built file has
    # moved to a new directory.
    wheel_filename = wkctx.wheels_downloads / wheel_filename.name

    return BuildSequenceEntry(
        name=canonicalize_name(req.name),
        version=resolved_version,
        prebuilt=prebuilt,
        download_url=source_download_url,
        wheel_filename=wheel_filename,
        skipped=use_exiting_wheel,
    )


def _is_wheel_built(
    wkctx: context.WorkContext,
    dist_name: str,
    resolved_version: Version,
    wheel_server_urls: list[str],
) -> pathlib.Path | None:
    req = Requirement(f"{dist_name}=={resolved_version}")

    try:
        logger.info(
            "checking if a suitable wheel for %s was already built on %s",
            req,
            wheel_server_urls,
        )
        url, _ = wheels.resolve_prebuilt_wheel(
            ctx=wkctx,
            req=req,
            wheel_server_urls=wheel_server_urls,
        )
        logger.info("found candidate wheel %s", url)
        pbi = wkctx.package_build_info(req)
        build_tag_from_settings = pbi.build_tag(resolved_version)
        build_tag = build_tag_from_settings if build_tag_from_settings else (0, "")
        wheel_basename = resolver.extract_filename_from_url(url)
        _, _, build_tag_from_name, _ = parse_wheel_filename(wheel_basename)
        existing_build_tag = build_tag_from_name if build_tag_from_name else (0, "")
        if (
            existing_build_tag[0] > build_tag[0]
            and existing_build_tag[1] == build_tag[1]
        ):
            raise ValueError(
                f"{dist_name}: changelog for version {resolved_version} is inconsistent. Found build tag {existing_build_tag} but expected {build_tag}"
            )
        if existing_build_tag != build_tag:
            logger.info(
                f"candidate wheel build tag {existing_build_tag} does not match expected build tag {build_tag}"
            )
            return None

        wheel_filename: pathlib.Path | None = None
        if url.startswith(wkctx.wheel_server_url):
            logging.debug("found wheel on local server")
            wheel_filename = wkctx.wheels_downloads / wheel_basename
            if not wheel_filename.exists():
                logger.info("wheel not found in local cache, preparing to download")
                wheel_filename = None

        if not wheel_filename:
            # if the found wheel was on an external server, then download it
            logger.info("downloading wheel from %s", url)
            wheel_filename = wheels.download_wheel(req, url, wkctx.wheels_downloads)

        return wheel_filename
    except Exception:
        logger.debug(
            "could not locate prebuilt wheel %s-%s on %s",
            dist_name,
            resolved_version,
            wheel_server_urls,
            exc_info=True,
        )
        logger.info("could not locate prebuilt wheel")
        return None


def _build_parallel(
    wkctx: context.WorkContext,
    resolved_version: Version,
    req: Requirement,
    source_download_url: str,
    force: bool,
    cache_wheel_server_url: str | None,
) -> BuildSequenceEntry:
    """
    This function runs in a thread to manage the build of a single package.
    """
    with req_ctxvar_context(req, resolved_version):
        return _build(
            wkctx=wkctx,
            resolved_version=resolved_version,
            req=req,
            source_download_url=source_download_url,
            force=force,
            cache_wheel_server_url=cache_wheel_server_url,
        )


class ParallelBuildManager:
    """Manages the logic for determining which nodes can be built in parallel."""

    def __init__(
        self, wkctx: context.WorkContext, graph: dependency_graph.DependencyGraph
    ):
        self.wkctx = wkctx
        self.graph = graph
        self.built_node_keys: set[str] = set()
        # Cache remaining nodes for efficiency - initialize with all non-root nodes
        self._remaining_nodes: DependencyNodeList = [
            node for node in graph.nodes.values() if node.key != dependency_graph.ROOT
        ]

    def _find_buildable_nodes(
        self, nodes_to_build: DependencyNodeList
    ) -> DependencyNodeList:
        """Find nodes that can be built (all build dependencies and their install dependencies are built)."""
        buildable_nodes: DependencyNodeList = []

        for node in nodes_to_build:
            with req_ctxvar_context(Requirement(node.canonicalized_name), node.version):
                # Get all build dependencies (build-system, build-backend, build-sdist)
                build_deps: DependencyNodeList = [
                    edge.destination_node
                    for edge in node.children
                    if edge.req_type.is_build_requirement
                ]

                # Collect all dependencies that must be built before this node can be built
                all_required_deps: set[str] = set()

                # Add direct build dependencies
                for build_dep in build_deps:
                    all_required_deps.add(build_dep.key)

                    # Add installation dependencies of each build dependency
                    install_deps_of_build_dep = [
                        edge.destination_node
                        for edge in build_dep.children
                        if edge.req_type.is_install_requirement
                    ]
                    for install_dep in install_deps_of_build_dep:
                        all_required_deps.add(install_dep.key)

                # A node can be built when all required dependencies are built
                unbuilt_deps: set[str] = set(
                    dep_key
                    for dep_key in all_required_deps
                    if dep_key not in self.built_node_keys
                )

                if not unbuilt_deps:
                    logger.info(
                        "ready to build, have all build dependencies and their install dependencies: %s",
                        sorted(all_required_deps),
                    )
                    buildable_nodes.append(node)
                else:
                    logger.info(
                        "waiting for build dependencies and their install dependencies: %s",
                        sorted(unbuilt_deps),
                    )

        return buildable_nodes

    def _filter_for_exclusive_builds(
        self, buildable_nodes: DependencyNodeList
    ) -> DependencyNodeList:
        """Filter buildable nodes to handle exclusive build requirements."""
        # Check if any buildable node requires exclusive build (exclusive_build == True)
        exclusive_nodes: DependencyNodeList = [
            node
            for node in buildable_nodes
            if self.wkctx.settings.package_build_info(
                node.canonicalized_name
            ).exclusive_build
        ]
        if exclusive_nodes:
            # Only build the first exclusive node this round
            filtered_nodes = [exclusive_nodes[0]]
            logger.info(
                f"{exclusive_nodes[0].canonicalized_name}: requires exclusive build, running it alone this round."
            )
            return filtered_nodes

        return buildable_nodes

    def get_nodes_ready_to_build(self) -> DependencyNodeList:
        """Get the list of nodes that are ready to be built in this round."""
        buildable_nodes = self._find_buildable_nodes(self._remaining_nodes)

        if not buildable_nodes:
            # If we can't build anything but still have nodes, we have a cycle
            remaining: list[str] = [n.key for n in self._remaining_nodes]
            logger.info("have already built: %s", sorted(self.built_node_keys))
            raise ValueError(f"Circular dependency detected among: {remaining}")

        logger.info(
            "ready to build: %s",
            sorted(n.key for n in buildable_nodes),
        )

        # Handle exclusive builds
        buildable_nodes = self._filter_for_exclusive_builds(buildable_nodes)

        return buildable_nodes

    def mark_node_built(self, node: dependency_graph.DependencyNode) -> None:
        """Mark a node as built."""
        self.built_node_keys.add(node.key)
        # Remove from remaining nodes cache for efficiency
        if node in self._remaining_nodes:
            self._remaining_nodes.remove(node)

    def have_remaining_nodes(self) -> bool:
        """Check if there are any nodes left to build."""
        return bool(self._remaining_nodes)

    def get_built_nodes(self) -> DependencyNodeList:
        """Get all nodes that have been built."""
        return [
            node
            for node in self.graph.nodes.values()
            if node.key in self.built_node_keys
        ]

    def is_node_built(self, node: dependency_graph.DependencyNode) -> bool:
        """Check if a specific node has been built."""
        return node.key in self.built_node_keys

    def get_build_progress(self) -> tuple[int, int]:
        """Get build progress as (built_count, total_count)."""
        total_nodes = len(
            [
                node
                for node in self.graph.nodes.values()
                if node.key != dependency_graph.ROOT
            ]
        )
        built_count = len(self.built_node_keys)
        return built_count, total_nodes


@click.command()
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="rebuild wheels even if they have already been built",
)
@click.option(
    "-c",
    "--cache-wheel-server-url",
    "cache_wheel_server_url",
    help="url to a wheel server from where fromager can check if it had already built the wheel",
)
@click.option(
    "-m",
    "--max-workers",
    type=int,
    default=None,
    help="maximum number of parallel workers to run (default: unlimited)",
)
@click.argument("graph_file")
@click.pass_obj
def build_parallel(
    wkctx: context.WorkContext,
    graph_file: str,
    force: bool,
    cache_wheel_server_url: str | None,
    max_workers: int | None,
) -> None:
    """Build wheels in parallel based on a dependency graph

    GRAPH_FILE is a graph.json file containing the dependency relationships between packages

    Performs parallel builds of wheels based on their dependency relationships.
    Packages that have no dependencies or whose dependencies are already built
    can be built concurrently. By default, all possible packages are built in
    parallel. Use --max-workers to limit the number of concurrent builds.

    """
    wkctx.enable_parallel_builds()

    server.start_wheel_server(wkctx)
    wheel_server_urls: list[str] = [wkctx.wheel_server_url]
    if cache_wheel_server_url:
        # put after local server so we always check local server first
        wheel_server_urls.append(cache_wheel_server_url)

    if force:
        logger.info(f"rebuilding all wheels even if they exist in {wheel_server_urls}")
    else:
        logger.info(
            f"skipping builds for versions of packages available at {wheel_server_urls}"
        )

    # Load the dependency graph
    logger.info("reading dependency graph from %s", graph_file)
    graph: dependency_graph.DependencyGraph
    graph = dependency_graph.DependencyGraph.from_file(graph_file)

    # Initialize the parallel build manager
    build_manager = ParallelBuildManager(wkctx, graph)

    # Get total count for progress tracking
    total_nodes = len(
        [n for n in graph.nodes.values() if n.key != dependency_graph.ROOT]
    )
    logger.info("found %d packages to build", total_nodes)

    # A node can be built when all of its build dependencies are built
    entries: list[BuildSequenceEntry] = []

    with progress.progress_context(total=total_nodes) as progressbar:

        def update_progressbar_cb(
            future: concurrent.futures.Future[BuildSequenceEntry],
        ) -> None:
            """Immediately update the progress when when a task is done"""
            progressbar.update()

        while build_manager.have_remaining_nodes():
            # Get nodes that are ready to be built in this round
            buildable_nodes = build_manager.get_nodes_ready_to_build()

            # Build up to max_workers nodes concurrently (or all if max_workers is None)
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers
            ) as executor:
                futures: list[concurrent.futures.Future[BuildSequenceEntry]] = []
                reqs: list[Requirement] = []
                logger.info(
                    "starting to build: %s", sorted(n.key for n in buildable_nodes)
                )
                for node in buildable_nodes:
                    req = Requirement(f"{node.canonicalized_name}=={node.version}")
                    reqs.append(req)
                    future = executor.submit(
                        _build_parallel,
                        wkctx=wkctx,
                        resolved_version=node.version,
                        req=req,
                        source_download_url=node.download_url,
                        force=force,
                        cache_wheel_server_url=cache_wheel_server_url,
                    )
                    future.add_done_callback(update_progressbar_cb)
                    futures.append(future)

                # Wait for all builds to complete
                for node, future in zip(buildable_nodes, futures, strict=True):
                    try:
                        entry = future.result()
                        entries.append(entry)
                        build_manager.mark_node_built(node)
                        # progress bar is updated in callback
                    except Exception as e:
                        logger.error(f"Failed to build {node.key}: {e}")
                        raise

    metrics.summarize(wkctx, "Building in parallel")
    _summary(wkctx, entries)


build_parallel._fromager_show_build_settings = True  # type: ignore
