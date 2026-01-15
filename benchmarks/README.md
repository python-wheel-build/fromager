# Fromager Benchmarks

Performance benchmarks for Fromager, testing core operations using direct API calls.

## Philosophy

Benchmarks should be as close to Fromager's implementation as possible:

- **Direct API calls only** — No custom logic or synthetic reimplementations
- **Follow unit test patterns** — Tests mirror Fromager's existing test structure
- **Fail on API changes** — Benchmarks break when Fromager changes (correct behavior)
- **Zero maintenance overhead** — No separate logic to maintain when Fromager evolves

## Quick Start

```bash
# Run all benchmarks
hatch run benchmark:run

# Run fast benchmarks only (skip integration tests)
hatch run benchmark:fast

# Run integration benchmarks only
hatch run benchmark:run -m "integration"

# Compare your branch against main (see below for full workflow)
hatch run benchmark:run --benchmark-compare=main
```

## Comparing Against Main Locally

To compare your branch against `main`:

```bash
# 1. Save baseline on main
git stash                                          # Save uncommitted changes
git checkout main
hatch run benchmark:run --benchmark-save=main
git checkout -                                     # Return to your branch
git stash pop                                      # Restore changes

# 2. Run comparison
hatch run benchmark:run --benchmark-compare=main
```

**Interpreting results:**
- **Ratio < 1.0** — Your branch is faster (improvement)
- **Ratio = 1.0** — No change
- **Ratio > 1.15** — Your branch is slower (investigate)

## Benchmark Types

### Component Benchmarks

Fast, isolated tests for individual Fromager modules. These test core operations like:

- Constraint parsing and version satisfaction
- Dependency graph construction and traversal
- Build order computation
- Version matching and caching behavior

### Integration Benchmarks

End-to-end tests using a local PyPI server for network isolation. These test complete Fromager workflows like version resolution and bootstrapping.

Integration benchmarks are marked with `@pytest.mark.integration` for filtering when needed.

## CI Workflows

### PR and Main (`benchmarks.yml`)

Runs on every PR and push to main, excluding tests marked `@pytest.mark.slow`.

Current benchmarks complete in ~12 seconds. Mark expensive future benchmarks as `@pytest.mark.slow` to exclude them from regular CI.

### Nightly (`benchmarks-nightly.yml`)

- Runs daily at 2 AM UTC (skips if no commits in 24 hours)
- Runs all benchmarks including those marked `slow`
- **Triggered on PRs by adding the `run-benchmarks` label**

### Backfill (`benchmark-backfill.yml`)

- Manual trigger for historical data
- Runs benchmarks across a range of commits

## Infrastructure

### Local PyPI Server

Integration benchmarks use Python's built-in `http.server` to serve a PEP 503-compliant package index. This provides:

- Network isolation (no external dependencies)
- Reproducible test conditions
- Fast startup (session-scoped fixture)

### pytest-benchmark

All benchmarks use pytest-benchmark for:

- Statistical analysis (mean, stddev, rounds)
- Baseline comparisons
- JSON export for CI tracking

## Adding Benchmarks

```python
def test_my_operation(benchmark):
    from fromager.my_module import my_function

    data = prepare_test_data()  # Setup: NOT measured

    def operation():
        return my_function(data)

    result = benchmark(operation)  # Measured
    assert result == expected  # Verify correctness
```

**Guidelines:**
1. Use direct Fromager API calls only
2. Keep setup outside the measured function
3. Always assert correctness
4. Use `@pytest.mark.integration` for tests requiring fixtures

## Directory Structure

```
benchmarks/
├── conftest.py         # Marker and fixture registration
├── pytest.ini          # pytest configuration
├── test_resolution.py  # Component benchmarks
├── test_integration.py # Integration benchmarks
└── fixtures/
    └── pypi_server.py  # Local PyPI server fixture
```

## Resources

- [pytest-benchmark docs](https://pytest-benchmark.readthedocs.io/)
- [CodSpeed docs](https://docs.codspeed.io/)
- [PEP 503 - Simple Repository API](https://peps.python.org/pep-0503/)
