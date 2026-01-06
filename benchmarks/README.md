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

**In CI:** CodSpeed automatically posts an **Impact Report** comment on pull requests showing performance changes. This is the primary interface for reviewing benchmark results.

## Benchmark Types

### Component Benchmarks (`test_resolution.py`)

Fast, isolated tests for CPU-bound, pure Python operations. These run on every PR using CodSpeed's CPU simulation mode for deterministic, hardware-independent measurements.

Examples: constraint parsing, version satisfaction, graph operations.

### Integration Benchmarks (`test_integration.py`)

End-to-end tests using a local PyPI server for network isolation. These test complete workflows involving I/O, network, and system calls.

Integration benchmarks are marked with `@pytest.mark.integration` and use CodSpeed's walltime mode on Macro Runners for accurate real-world measurements.

## CI Workflows

### Component Benchmarks (`benchmarks.yml`)

- Runs on every PR and push to main
- Uses CPU simulation on `ubuntu-latest`
- Excludes tests marked `@pytest.mark.slow` or `@pytest.mark.integration`

### Integration Benchmarks (`benchmarks-integration.yml`)

- Runs on every PR and push to main
- Uses walltime mode on CodSpeed Macro Runners (`codspeed-macro`)
- Only runs tests marked `@pytest.mark.integration`
- Excludes tests marked `@pytest.mark.slow`

### Nightly (`benchmarks-nightly.yml`)

- Runs daily at 2 AM UTC (skips if no commits in 24 hours)
- Runs **all** benchmarks including those marked `@pytest.mark.slow`
- Split into two jobs: component (simulation) and integration (walltime)
- **Triggered on PRs by adding the `run-benchmarks` label**

### Backfill (`benchmark-backfill.yml`)

Manually triggered workflow to populate CodSpeed with historical baseline data.

**How it works:**

1. Checks out each historical commit in the specified range
2. Copies the `benchmarks/` directory from a source branch (default: `main`)
3. Installs the project using the historical commit's dependencies
4. Extracts benchmark dependencies from the source branch's `pyproject.toml`
5. Runs pytest directly (bypasses missing Hatch environments in old commits)

This "Runtime Dependency Injection" pattern ensures:

- Historical code runs with its original dependencies (valid performance data)
- Modern benchmarks run against old code (consistent test coverage)
- Single source of truth for benchmark dependencies (no duplication)

**Jobs:**

- **Component benchmarks** (always runs) - CPU simulation on `ubuntu-latest`
- **Integration benchmarks** (optional) - Walltime on `codspeed-macro`, only when `include_integration` is enabled

**Inputs:**

| Input | Description | Default |
| ----- | ----------- | ------- |
| `from_commit` | Start commit SHA (older) | Required |
| `to_commit` | End commit SHA (newer) | `HEAD` |
| `benchmark_source` | Branch to copy benchmarks from | `main` |
| `benchmark_set` | `fast` (excludes `@pytest.mark.slow`) or `full` | `fast` |
| `include_integration` | Run integration benchmarks on Macro Runners | `false` |

**Limitations:**

- Maximum **200 commits** per run (or **128** when `include_integration` is enabled, since both component and integration jobs run per commit). GitHub Actions has a hard limit of 256 jobs per matrix. If the range exceeds the limit, older commits are skipped. Run the workflow multiple times with smaller ranges to backfill larger histories.
- **API drift:** Benchmarks will fail on commits where Fromager's API differs from what the current benchmarks expect. Only backfill ranges where the relevant APIs remained stable.
- Integration backfill uses Macro Runner minutes (enable only when needed)

**Data Immutability:**

CodSpeed benchmark data is immutable. Re-running benchmarks for a commit that already has data will **append** new results rather than replace existing ones. This means:

- Backfill is ideal for **populating initial baselines** or **adding new benchmarks**
- Backfill **cannot retroactively fix** benchmark definitions on historical commits
- If a benchmark is renamed, CodSpeed treats it as a new benchmark (old one shows as "skipped")
- To exclude bad data, use the **"Ignore"** button in the CodSpeed dashboard

## Infrastructure

### CodSpeed

Key things to know:

- **Simulation mode** is deterministic and free but cannot measure system calls, I/O, or network operations
- **Walltime mode** captures everything but consumes Macro Runner quota and has slight variance from hardware noise
- **Macro Runners** require a GitHub Organization (not personal accounts) and use ARM64 hardware
- **Data is append-only** — re-runs append data rather than replace; use "Ignore" in dashboard to exclude bad runs
- **GitHub Actions** limits matrix jobs to 256 per workflow run (backfill is capped at 200 commits)

For current quotas and limits, see [CodSpeed Pricing](https://codspeed.io/pricing) and [Macro Runners docs](https://codspeed.io/docs/features/macro-runners).

### Multi-Architecture Caching

Macro Runners use ARM64 while standard runners use x86_64. If you add `actions/cache` to benchmark workflows (e.g., for virtualenvs), you **must** include the architecture in cache keys:

```yaml
- uses: actions/cache@v4
  with:
    key: benchmark-${{ runner.os }}-${{ runner.arch }}-${{ hashFiles('pyproject.toml') }}
```

Mixing architectures will cause binary incompatibility crashes.

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

Before adding a benchmark, ask:

1. **Is this Fromager code?** Don't benchmark third-party libraries (e.g., `packaging`, `lru_cache`)
2. **Is this a hot path?** Focus on operations that run frequently during resolution
3. **Can performance actually change?** Trivial wrappers around stdlib won't regress

### Basic Pattern

```python
def test_my_operation(benchmark):
    from fromager.my_module import my_function

    data = prepare_test_data()  # Setup: NOT measured

    def operation():
        return my_function(data)

    result = benchmark(operation)  # Measured
    assert result == expected  # Verify correctness
```

### Benchmarking Cached Functions

For functions with `@lru_cache`, use `benchmark.pedantic()` to clear caches before each iteration without including the cache-clear time in measurements:

```python
def test_cached_operation(benchmark):
    from fromager.my_module import cached_function

    def setup_iteration():
        cached_function.cache_clear()  # Not measured
        return (), {}

    def operation():
        return cached_function(arg)

    result = benchmark.pedantic(
        operation,
        setup=setup_iteration,
        rounds=20,
        iterations=1,
    )
    assert result == expected
```

**Why clear caches?** Without clearing, you're benchmarking Python's `lru_cache` (dict lookup), not your code. Cold-cache benchmarks catch algorithm regressions that warm-cache benchmarks would miss.

**Note:** The `setup` function runs before every measurement round. Keep it lightweight (just cache clearing). Don't put heavy data preparation in `setup` or your benchmark will time out.

### Guidelines

1. Use direct Fromager API calls only
2. Keep setup outside the measured function
3. Always assert correctness
4. Use `@pytest.mark.integration` for tests requiring I/O or network
5. Use `benchmark.pedantic()` when cache clearing is needed

## Directory Structure

```text
benchmarks/
├── conftest.py           # Marker and fixture registration
├── pytest.ini            # pytest configuration
├── test_resolution.py    # Component benchmarks
├── test_integration.py   # Integration benchmarks
├── fixtures/
│   └── pypi_server.py    # Local PyPI server fixture
└── scripts/
    └── extract_deps.py   # Extracts benchmark deps from pyproject.toml
```

## CodSpeed Instruments

Fromager benchmarks use two different CodSpeed instruments based on what they measure:

| Instrument         | Runner           | Use Case                       | Limitations                                                |
| ------------------ | ---------------- | ------------------------------ | ---------------------------------------------------------- |
| **CPU Simulation** | `ubuntu-latest`  | Pure Python, CPU-bound code    | Cannot measure system calls, I/O, or network               |
| **Walltime**       | `codspeed-macro` | I/O, network, subprocess calls | Consumes Macro Runner quota, org accounts only, ARM64      |

**Why the split?** CPU simulation provides deterministic measurements but ignores system calls entirely. Integration benchmarks that test HTTP requests, file I/O, and subprocess calls would show misleading results (or warnings about unmeasured system call time) without walltime mode.

For more details, see [CodSpeed Walltime docs](https://codspeed.io/docs/instruments/walltime).

## Resources

- [pytest-benchmark docs](https://pytest-benchmark.readthedocs.io/)
- [CodSpeed docs](https://docs.codspeed.io/)
- [CodSpeed Walltime Instrument](https://codspeed.io/docs/instruments/walltime)
- [PEP 503 - Simple Repository API](https://peps.python.org/pep-0503/)
