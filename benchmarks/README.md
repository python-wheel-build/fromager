# Fromager Benchmarks

Performance benchmarks for Fromager, a tool for rebuilding complete dependency trees of Python wheels from source.

## Table of Contents

- [Why Benchmarks?](#why-benchmarks)
- [Quick Start](#quick-start)
- [Understanding the Output](#understanding-the-output)
- [How It Works](#how-it-works)
  - [Local Benchmarking with pytest-benchmark](#local-benchmarking-with-pytest-benchmark)
  - [CI Benchmarking with CodSpeed](#ci-benchmarking-with-codspeed)
  - [Network Isolation with Local PyPI](#network-isolation-with-local-pypi)
  - [Subprocess Isolation with uv Shim](#subprocess-isolation-with-uv-shim)
  - [Memory Profiling with pytest-memray](#memory-profiling-with-pytest-memray)
- [Benchmark Categories](#benchmark-categories)
- [Adding New Benchmarks](#adding-new-benchmarks)
- [CI Workflows](#ci-workflows)
- [Directory Structure](#directory-structure)
- [Troubleshooting](#troubleshooting)
- [Resources](#resources)

---

## Why Benchmarks?

Fromager processes hundreds of packages during a typical bootstrap, each requiring version resolution, source acquisition, patching, and wheel building. Performance regressions in Fromager's core logic compound across these operations.

**The challenge:** Wall-clock benchmarks in shared CI environments vary 10-20% due to noise (other processes, network latency, disk I/O). A genuine 5% regression becomes indistinguishable from CI variance.

**Our solution:** We use two complementary approaches:
1. **Locally:** pytest-benchmark for quick iteration during development
2. **In CI:** CodSpeed for noise-resistant measurements using CPU instruction counting

---

## Quick Start

```bash
# Run all benchmarks (uses pytest-benchmark locally)
hatch run benchmark:run

# Run fast benchmarks only (skip slow and integration tests)
hatch run benchmark:fast

# Compare your changes against a baseline
hatch run benchmark:run --benchmark-save=baseline
# ... make your changes ...
hatch run benchmark:compare baseline

# Export results to JSON for external analysis
hatch run benchmark:json
```

---

## Understanding the Output

When you run benchmarks, you'll see output like this:

```
-------------------------------- benchmark: 3 tests --------------------------------
Name                                   Mean        StdDev      Rounds
------------------------------------------------------------------------------------
test_constraint_add_and_check          0.85ms      0.05ms      100
test_graph_serialization               1.20ms      0.08ms      100
test_python_version_matching_hot       0.12ms      0.01ms      200
------------------------------------------------------------------------------------
```

**What these columns mean:**
- **Name** — The benchmark test function name
- **Mean** — Average execution time (the primary metric to compare)
- **StdDev** — Standard deviation; lower values mean more consistent measurements
- **Rounds** — How many times the benchmark ran; more rounds = more statistical confidence

**When comparing against a baseline:**
```
Name                             Mean (now)    Mean (base)   Ratio
--------------------------------------------------------------------
test_constraint_add_and_check    0.87ms        0.85ms        1.02x
```

- **Ratio < 1.0** — Your code is faster (improvement!)
- **Ratio = 1.0** — No change
- **Ratio > 1.15** — Your code is slower; investigate before merging

---

## How It Works

### Local Benchmarking with pytest-benchmark

[pytest-benchmark](https://pytest-benchmark.readthedocs.io/) is a pytest plugin that measures execution time of your code. It handles the complexity of accurate timing: warm-up runs, garbage collection, statistical analysis, and comparison against saved baselines.

**How we use it:**
```python
def test_constraint_satisfaction(benchmark):
    """The 'benchmark' fixture is provided by pytest-benchmark."""
    from fromager.constraints import Constraints

    constraints = Constraints()
    constraints.add_constraint("numpy>=1.20,<2.0")

    # This function will be called many times to get accurate timing
    def check_constraint():
        return constraints.is_satisfied_by("numpy", Version("1.25.0"))

    result = benchmark(check_constraint)  # Measures execution time
    assert result is True  # Always verify correctness too!
```

The `benchmark` fixture automatically:
- Warms up the code before measuring
- Runs multiple iterations to get statistical significance
- Disables garbage collection during measurement
- Calculates mean, standard deviation, and other statistics

---

### CI Benchmarking with CodSpeed

**The problem with wall-clock time in CI:** GitHub Actions runners are shared machines. Other jobs, network conditions, and system processes cause timing variations of 10-20%. This noise masks real performance regressions.

**CodSpeed's solution:** Instead of measuring wall-clock time, [CodSpeed](https://codspeed.io/) counts CPU instructions executed. Instruction counts are deterministic—the same code always executes the same number of instructions, regardless of system load.

**How it works in our CI:**
1. When you add the `run-benchmarks` label to a PR, our GitHub Action triggers
2. CodSpeed's action runs your benchmarks inside Valgrind (an instrumentation tool)
3. Valgrind counts every CPU instruction executed
4. CodSpeed compares instruction counts against the main branch baseline
5. CodSpeed posts a comment on your PR showing any regressions

**Why this matters:**
- A 5% regression is clearly visible (not hidden in noise)
- Results are reproducible across different CI runs
- No need for dedicated benchmark hardware

**Configuration:** The `CODSPEED_TOKEN` secret must be configured in the repository for CI benchmarks to report to the CodSpeed dashboard.

---

### Network Isolation with Local PyPI

**The problem:** Real package resolution hits PyPI servers. Network latency varies, servers may be slow, and results become non-deterministic.

**Our solution:** The `local_pypi` fixture starts a local [pypiserver](https://github.com/pypiserver/pypiserver) instance:

```python
@pytest.fixture(scope="session")
def local_pypi(tmp_path_factory):
    """Starts a local PyPI server for the entire test session."""
    # Downloads packages from requirements/packages.txt
    # Starts pypiserver on localhost:18080
    # All package resolution uses this local server
```

**How it's used:**
```python
@pytest.mark.integration
def test_resolution_benchmark(benchmark, configured_env):
    """configured_env sets UV_INDEX_URL to point to local PyPI."""
    # Any package resolution now hits localhost, not the internet
    result = benchmark(resolve_packages)
```

The `configured_env` fixture automatically sets:
- `UV_INDEX_URL` → `http://localhost:18080/simple`
- `PIP_INDEX_URL` → `http://localhost:18080/simple`
- `UV_NO_PROGRESS` → `1` (cleaner output)

---

### Subprocess Isolation with uv Shim

**The problem:** Fromager calls external tools like `uv` via subprocess. The actual execution time of `uv` varies based on many factors (disk cache, network, system load). This variance pollutes our measurements of Fromager's own code.

**Our solution:** The `uv_shim` fixture creates a fake `uv` binary that does nothing but exit immediately:

```python
# This is what the shim does (simplified):
#!/usr/bin/env python3
import time
time.sleep(0.01)  # Fixed 10ms delay
sys.exit(0)  # Instant success
```

**How it works:**
1. The fixture creates a temporary executable script
2. The `with_uv_shim` fixture prepends this script's directory to `PATH`
3. When Fromager calls `subprocess.run(["uv", ...])`, it finds our shim first
4. The shim returns instantly with success
5. We measure only Fromager's Python code, not `uv`'s execution

**When to use it:**
```python
@pytest.mark.integration
def test_build_workflow(benchmark, with_uv_shim, subprocess_timer):
    """with_uv_shim makes 'uv' calls instant and deterministic."""

    with subprocess_timer.measure():
        result = benchmark(run_fromager_build)

    # subprocess_timer tells us how much time was spent in subprocesses
    print(f"Subprocess calls: {subprocess_timer.call_count}")
    print(f"Overhead ratio: {subprocess_timer.overhead_ratio}")
```

The `subprocess_timer` fixture patches `subprocess.run` to measure:
- **call_count** — How many subprocesses were spawned
- **total_time** — Total time spent waiting for subprocesses
- **overhead_ratio** — Fraction of time spent in Fromager's Python code (vs. subprocesses)

---

### Memory Profiling with pytest-memray

[pytest-memray](https://pytest-memray.readthedocs.io/) tracks memory allocations during test execution. This helps identify memory leaks or excessive allocations.

```bash
# Run with memory profiling
hatch run benchmark:memory

# Save detailed results for analysis
hatch run benchmark:memory --memray-bin-path=./memray-results
```

**Note:** pytest-memray only works on Linux and macOS (not Windows).

**Important:** Memory profiling and CodSpeed cannot run together—both instrument the Python interpreter in ways that conflict. Our CI runs them as separate jobs.

---

## Benchmark Categories

| Category | File | What it Tests | Speed |
|----------|------|---------------|-------|
| **Component** | `test_resolution.py` | Pure Python functions (Constraints, DependencyGraph, resolver) | Fast (< 1 second each) |
| **Integration** | `test_integration.py` | Full workflows with fixtures (file I/O, subprocess calls) | Slow (may take seconds) |

**Markers to control what runs:**
```bash
# Skip slow benchmarks
hatch run benchmark:run -m "not slow"

# Skip integration benchmarks
hatch run benchmark:run -m "not integration"

# Only run integration benchmarks
hatch run benchmark:run -m "integration"
```

---

## Adding New Benchmarks

### Basic Benchmark

```python
def test_my_operation(benchmark):
    """Benchmark a simple operation."""
    from fromager.my_module import my_function

    # Setup: runs once, NOT measured
    data = prepare_test_data()

    # This function is what gets measured (runs many times)
    def operation():
        return my_function(data)

    result = benchmark(operation)

    # Always verify correctness!
    assert result == expected_value
```

### Benchmark with Fixtures

```python
@pytest.mark.integration
@pytest.mark.slow
def test_full_workflow(benchmark, configured_env, subprocess_timer):
    """Benchmark a complete workflow with network and subprocess isolation."""

    def workflow():
        with subprocess_timer.measure():
            return run_complete_workflow()

    result = benchmark(workflow)

    # Record extra metrics for analysis
    benchmark.extra_info["subprocess_calls"] = subprocess_timer.call_count
    benchmark.extra_info["overhead_ratio"] = subprocess_timer.overhead_ratio

    assert result.success
```

### Guidelines

1. **Keep setup outside the measured function** — Only measure the code you're interested in
2. **Always assert correctness** — A fast but wrong function is useless
3. **Use appropriate markers** — Mark slow tests with `@pytest.mark.slow`
4. **Add extra_info for debugging** — `benchmark.extra_info["key"] = value` appears in JSON output

---

## CI Workflows

### `benchmarks.yml` — PR and Main Branch

**Triggers:**
- Push to `main` branch (updates baseline)
- PRs with the `run-benchmarks` label

**What it does:**
1. Runs fast benchmarks with CodSpeed (instruction counting)
2. CodSpeed compares against main branch baseline
3. Posts results as a PR comment
4. Also generates JSON artifacts for local comparison

**Jobs:**
- `benchmark-cpu` — CodSpeed benchmarks
- `benchmark-memory` — Memory profiling (separate to avoid conflicts)

### `benchmarks-nightly.yml` — Nightly Integration

**Triggers:**
- Cron schedule: 2 AM UTC daily
- Manual trigger via GitHub Actions UI

**What it does:**
1. Starts a Docker container running pypiserver
2. Runs integration benchmarks with subprocess tracing enabled
3. Uses `CODSPEED_VALGRIND_ARGS="--trace-children=yes"` to measure subprocess execution
4. Runs memory profiling on integration tests
5. Stores artifacts for 90 days

---

## Directory Structure

```
benchmarks/
├── README.md              # This file
├── pytest.ini             # pytest configuration for benchmarks
├── conftest.py            # Shared fixtures and marker registration
│
├── fixtures/              # Reusable test fixtures
│   ├── __init__.py        # Exports all fixtures
│   ├── pypi_server.py     # local_pypi, configured_env
│   ├── uv_shim.py         # uv_shim, with_uv_shim
│   └── metrics.py         # SubprocessTimer, subprocess_timer
│
├── requirements/
│   └── packages.txt       # Packages for local PyPI server
│
├── test_resolution.py     # Fast, pure-Python benchmarks
└── test_integration.py    # Slow, full-workflow benchmarks
```

---

## Troubleshooting

### High Variance in Results

If you see high `StdDev` values:
1. Close resource-intensive applications
2. Increase the number of rounds: `--benchmark-min-rounds=20`
3. Run on a less busy machine

### Missing Module Errors

```bash
ModuleNotFoundError: No module named 'pytest_benchmark'
```

The benchmark dependencies are installed automatically when using the hatch environment. Simply run:
```bash
hatch run benchmark:run
```

### Debugging Benchmark Failures

Run benchmarks as regular tests (no timing):
```bash
hatch run benchmark:disable
```

### CodSpeed Not Reporting

1. Check that `CODSPEED_TOKEN` is set in repository secrets
2. Verify the PR has the `run-benchmarks` label
3. Check the GitHub Actions logs for errors

### Memory Profiling Fails

pytest-memray doesn't work on Windows. On macOS/Linux, ensure you have the benchmark dependencies installed.

---

## Resources

- **[pytest-benchmark docs](https://pytest-benchmark.readthedocs.io/)** — Local benchmarking plugin
- **[CodSpeed docs](https://docs.codspeed.io/)** — Noise-resistant CI benchmarks
- **[pytest-memray docs](https://pytest-memray.readthedocs.io/)** — Memory profiling
- **[pypiserver docs](https://github.com/pypiserver/pypiserver)** — Local PyPI server
