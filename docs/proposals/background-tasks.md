# Plan: Background Task Parallelization for Bootstrapper

## Context

The bootstrap process builds packages via a serial iterative LIFO stack. Version resolution (PyPI network calls) and source preparation (download + unpack) are pure I/O that block the main loop while the stack sits idle. By submitting these operations to a background thread pool as items are pushed onto the stack, we can overlap I/O with the main thread's serial processing, reducing total bootstrap time without changing build order.

The `exclusive_build` flag already exists in `PackageBuildInfo` and is the signal to drain the pool before an exclusive build starts.

---

## Phase 1: `PreparedSourceData` dataclass

**File:** `src/fromager/bootstrapper.py` (after `SourceBuildResult`, ~line 63)

New dataclass carrying the result of background I/O for PREPARE_SOURCE back to the main thread:

```python
@dataclasses.dataclass
class PreparedSourceData:
    """Result of background I/O pre-fetching for the PREPARE_SOURCE phase."""
    sdist_root_dir: pathlib.Path | None = None        # source build path: populated after download+unpack
    cached_wheel_filename: pathlib.Path | None = None  # source build path: found in cache
    cached_unpack_dir: pathlib.Path | None = None      # source build path: cached wheel unpack dir
    wheel_filename: pathlib.Path | None = None         # prebuilt path: downloaded wheel
    unpack_dir: pathlib.Path | None = None             # prebuilt path: unpack dir
```

`server.update_wheel_mirror()` is already thread-safe, so the full `_download_prebuilt()` operation (download + create unpack dir + mirror update) can run in the background. `_create_unpack_dir()` is also safe (or can be made so), so source preparation is fully backgroundable.

---

## Phase 2: `WorkItem` changes

**File:** `src/fromager/bootstrapper.py` (WorkItem dataclass, ~line 110)

Add one field:

```python
bg_future: concurrent.futures.Future[typing.Any] | None = dataclasses.field(
    default=None, compare=False, repr=False
)
```

`compare=False, repr=False` avoids interference with dataclass ordering and logging.

---

## Phase 3: `Bootstrapper.__init__` changes

**File:** `src/fromager/bootstrapper.py` (~line 148)

- Add parameter `num_bg_threads: int = max(1, (os.cpu_count() or 2) // 2)`
- Store as `self._num_bg_threads = num_bg_threads`
- If `num_bg_threads > 0`, create:
  ```python
  self._bg_pool: concurrent.futures.ThreadPoolExecutor | None = concurrent.futures.ThreadPoolExecutor(
      max_workers=num_bg_threads, thread_name_prefix="fromager-bg"
  )
  ```
  Otherwise `self._bg_pool = None`.

---

## Phase 4: Thread safety — `BootstrapRequirementResolver`

**File:** `src/fromager/bootstrap_requirement_resolver.py`

- Add `self._cache_lock = threading.Lock()` in `__init__` (also add `import threading`)
- Wrap `get_cached_resolution()` body with `with self._cache_lock:`
- Wrap `cache_resolution()` body with `with self._cache_lock:`

A single lock is sufficient — the critical section is a single dict read/write (O(1)).

---

## Phase 5: `_get_background_work` method

**File:** `src/fromager/bootstrapper.py` (new method, near `_dispatch_phase`)

```python
def _get_background_work(
    self, item: WorkItem
) -> typing.Callable[[], typing.Any] | None:
```

Returns a zero-argument callable or `None`.

**RESOLVE-phase items:**
Return a callable that performs the full resolution: calls `self._resolver.resolve(req, req_type, parent_req, return_all_versions)` where `parent_req` is derived from `item.why_snapshot` at submission time (NOT `self.why`, which is main-thread mutable), and returns the `list[tuple[str, Version]]` result. The background task owns the resolution entirely; `_phase_resolve` on the main thread just waits for the future.

**PREPARE_SOURCE-phase items:**

- If `item.pbi_pre_built`: return callable that calls the full `_download_prebuilt()` (download wheel + create unpack dir + update mirror) and returns `PreparedSourceData(wheel_filename=<result>, unpack_dir=<result>)`
- If source build: return callable that calls `_find_cached_wheel()` then (if no cache) `_download_source()` + `_prepare_source()` + `_create_unpack_dir()`, returns `PreparedSourceData(...)` with appropriate fields populated

**All other phases:** Return `None`.

---

## Phase 6: `_drain_background_pool` method

**File:** `src/fromager/bootstrapper.py` (new method)

```python
def _drain_background_pool(self) -> None:
    if self._bg_pool is None:
        return
    self._bg_pool.shutdown(wait=True, cancel_futures=False)
    self._bg_pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=self._num_bg_threads, thread_name_prefix="fromager-bg"
    )
```

Shutdown+recreate is simpler than maintaining a separate list of pending futures. `cancel_futures=False` ensures all submitted tasks complete before rebuilding.

---

## Phase 7: Bootstrap loop changes

**File:** `src/fromager/bootstrapper.py`, `bootstrap()` method (~line 413)

After `stack.extend(new_items)`, submit background tasks for newly pushed items **in LIFO processing order** (same order the main loop will pop them):

```python
stack.extend(new_items)
if self._bg_pool is not None:
    for new_item in reversed(new_items):
        bg_work = self._get_background_work(new_item)
        if bg_work is not None:
            new_item.bg_future = self._bg_pool.submit(bg_work)
```

`reversed(new_items)` submits the item that lands on top of the stack first (the one the main loop reaches soonest). When the thread pool has fewer threads than pending background tasks, the most time-critical tasks — those with the least remaining time before the main thread needs their result — start first. Submitting after `extend` ensures the item is on the stack before the future starts (no race).

---

## Phase 8: `_phase_resolve` changes

**File:** `src/fromager/bootstrapper.py` (~line 1354)

All RESOLVE-phase items always have a background task submitted, so `_phase_resolve` unconditionally waits for the future:

```python
resolved_versions = item.bg_future.result()  # blocks if not done; re-raises background exceptions
```

One code path only: no fallback. The existing logic that converts `resolved_versions` into a `WorkItem` list continues unchanged below.

Since RESOLVE background tasks are always submitted, `_bg_pool` must always exist. If `num_bg_threads=0` is specified (disabling PREPARE_SOURCE parallelism), a minimum of 1 thread is still kept for resolution. Alternatively, use a dedicated single-thread resolver pool (`self._resolve_pool`) separate from the I/O pool (`self._bg_pool`) so that `num_bg_threads=0` can truly disable PREPARE_SOURCE background work while resolution still runs off-thread. The exact approach (one pool vs two) is an implementation decision, but the invariant — `item.bg_future` is always set for RESOLVE items — must hold.

---

## Phase 9: `_phase_prepare_source` changes

**File:** `src/fromager/bootstrapper.py` (~line 1461)

At the top of the method, wait for the background result if present:

```python
prepared: PreparedSourceData | None = None
if item.bg_future is not None:
    prepared = item.bg_future.result()  # blocks if not done; re-raises background exceptions
```

Then use `prepared` to skip already-done I/O:

- If prebuilt and `prepared.wheel_filename` + `prepared.unpack_dir` are set: skip the full `_download_prebuilt()` call (download, unpack dir creation, and mirror update were all done in background)
- If source and `prepared.sdist_root_dir` is set: skip `_download_source()` + `_prepare_source()` + `_create_unpack_dir()`, use result directly
- If source and `prepared.cached_wheel_filename` is set: use cached wheel path from background result
- If `prepared` is None (background disabled or phase was reached without a bg task): existing logic unchanged

Exceptions raised in the background task surface via `future.result()`, propagate through `_dispatch_phase`, and are caught by the existing `_handle_phase_error` machinery — correct behavior.

---

## Phase 10: `_phase_build` exclusive-build drain

**File:** `src/fromager/bootstrapper.py` (~line 1597)

At the top of `_phase_build`:

```python
pbi = self.ctx.package_build_info(item.req)
if pbi.exclusive_build:
    logger.info("%s requires exclusive build, draining background pool", item.req)
    self._drain_background_pool()
```

Placed before any build work begins. After the exclusive build completes the pool (now recreated empty) continues accepting new submissions.

---

## Phase 11: `finalize()` pool shutdown

**File:** `src/fromager/bootstrapper.py`, `finalize()` (~line 1852)

At the start of `finalize()`:

```python
if self._bg_pool is not None:
    self._bg_pool.shutdown(wait=True, cancel_futures=False)
    self._bg_pool = None
```

The pool is created in `__init__` and lives across all `bootstrap()` calls; `finalize()` is the natural cleanup point.

---

## Phase 12: CLI option

**File:** `src/fromager/commands/bootstrap.py` (~line 113)

Add Click option before `@click.argument("toplevel", ...)`:

```python
@click.option(
    "--bg-threads",
    "num_bg_threads",
    type=click.IntRange(min=0),
    default=max(1, (os.cpu_count() or 2) // 2),
    show_default=True,
    help="Number of background threads for parallel I/O pre-fetching. 0 disables background processing.",
)
```

Add `num_bg_threads: int` to function signature. Pass `num_bg_threads=num_bg_threads` to `Bootstrapper(...)`.

---

## Files to modify

| File | Changes |
| -- | -- |
| `src/fromager/bootstrapper.py` | New `PreparedSourceData`, `WorkItem.bg_future`, `Bootstrapper.__init__`, new `_get_background_work`, new `_drain_background_pool`, bootstrap loop, `_phase_prepare_source`, `_phase_build`, `finalize()` |
| `src/fromager/bootstrap_requirement_resolver.py` | `threading.Lock` for `_resolved_requirements` cache |
| `src/fromager/commands/bootstrap.py` | `--bg-threads` CLI option |

No new files. `server.update_wheel_mirror()` is already thread-safe; `_create_unpack_dir()` is safe (or can be made so with `exist_ok=True`). No changes to `sources.py` are expected — different packages use different source directories, so concurrent background tasks for different packages won't collide.

---

## Verification

```bash
# Type check changed files
hatch run mypy:check src/fromager/bootstrapper.py src/fromager/bootstrap_requirement_resolver.py src/fromager/commands/bootstrap.py

# Run targeted tests
hatch run test:test tests/test_bootstrapper.py tests/test_bootstrapper_iterative.py

# Lint
hatch run lint:fix src/fromager/bootstrapper.py src/fromager/bootstrap_requirement_resolver.py src/fromager/commands/bootstrap.py
```

New tests to add to `tests/test_bootstrapper_iterative.py`:

- `TestGetBackgroundWork` — returns `None` for non-I/O phases; returns callable for RESOLVE and PREPARE_SOURCE; RESOLVE callable uses `why_snapshot` not `self.why`
- `TestPhasePrepareSourceWithBgFuture` — uses background result to skip download/unpack; exception in background propagates correctly; falls back gracefully when `bg_future` is None
- `TestDrainBackgroundPool` — no-op when pool is None; pool is recreated after drain; all futures complete before return
- `TestExclusiveBuildBarrier` — `_phase_build` calls drain for `exclusive_build=True`; does not call drain for `exclusive_build=False`
