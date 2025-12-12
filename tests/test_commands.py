import pathlib
import typing
from unittest import mock

import click

from fromager import context
from fromager.commands import bootstrap, build
from fromager.dependency_graph import DependencyGraph


def get_option_names(cmd: click.Command) -> typing.Iterable[str]:
    return [o.name for o in cmd.params if o.name]


def test_bootstrap_parallel_options() -> None:
    expected: set[str] = set()
    expected.update(get_option_names(bootstrap.bootstrap))
    expected.update(get_option_names(build.build_parallel))
    # bootstrap-parallel enforces sdist_only=True and handles
    # graph_file internally.
    expected.discard("sdist_only")
    expected.discard("graph_file")

    assert set(get_option_names(bootstrap.bootstrap_parallel)) == expected


def test_calculate_optimal_max_workers_auto(
    tmp_context: context.WorkContext,
    e2e_path: pathlib.Path,
) -> None:
    """Test automatic max_workers calculation based on graph parallelism."""
    graph = DependencyGraph.from_file(e2e_path / "build-parallel" / "graph.json")

    # When user_max_workers is None, should use min(cpu_default, max_parallelism)
    with mock.patch("os.cpu_count", return_value=8):
        # cpu_default = min(32, 8+4) = 12
        # The graph has batches with max parallelism of 6 (from test_e2e_parallel_graph)
        result = build._calculate_optimal_max_workers(graph, tmp_context, None)
        # Should use the smaller of cpu_default (12) and max_parallelism (6)
        assert result == 6


def test_calculate_optimal_max_workers_user_specified(
    tmp_context: context.WorkContext,
    e2e_path: pathlib.Path,
) -> None:
    """Test that user-specified max_workers is respected."""
    graph = DependencyGraph.from_file(e2e_path / "build-parallel" / "graph.json")

    # User specifies 4 workers
    result = build._calculate_optimal_max_workers(graph, tmp_context, 4)
    assert result == 4

    # User specifies more workers than graph parallelism allows
    result = build._calculate_optimal_max_workers(graph, tmp_context, 100)
    assert result == 100  # Still respects user choice, just logs a warning


def test_calculate_optimal_max_workers_limited_by_cpu(
    tmp_context: context.WorkContext,
    e2e_path: pathlib.Path,
) -> None:
    """Test when CPU count limits the workers (cpu_default < max_parallelism)."""
    graph = DependencyGraph.from_file(e2e_path / "build-parallel" / "graph.json")

    # Simulate a machine with only 1 CPU
    with mock.patch("os.cpu_count", return_value=1):
        # cpu_default = min(32, 1+4) = 5
        # max_parallelism = 6 (largest batch in graph)
        result = build._calculate_optimal_max_workers(graph, tmp_context, None)
        # Should use min(5, 6) = 5 (limited by CPU)
        assert result == 5
