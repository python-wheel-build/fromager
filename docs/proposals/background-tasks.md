# Plan: Background Task Parallelization for Bootstrapper

## Context

The bootstrap process builds packages via a serial iterative LIFO stack. Version resolution (PyPI network calls) and source preparation (download + unpack) are pure I/O that block the main loop while the stack sits idle. By submitting these operations to a background thread pool as items are pushed onto the stack, we can overlap I/O with the main thread's serial processing, reducing total bootstrap time without changing build order.

The `exclusive_build` flag already exists in `PackageBuildInfo` and is the signal to drain the pool before an exclusive build starts.

---

## Phase 1: `PreparedSourceData` dataclass

**File:** `src/fromager/bootstrapper.py` (after `SourceBuildResult`, ~line 63)

New dataclass carrying the result of background I/O pre-fetching for PREPARE_SOURCE back to the main thread:

```python
@dataclasses.dataclass
class PreparedSourceData:
    """Result of background I/O pre-fetching for the PREPARE_SOURCE phase.

    For source builds, only sdist_root_dir (and optionally cached_wheel_filename
    / cached_unpack_dir) are populated. unpack_dir is always sdist_root_dir.parent
    and is never stored separately for the source path.

    For prebuilt builds, wheel_filename and unpack_dir are populated.
    """
    sdist_root_dir: pathlib.Path | None = None        # source build path: populated after download+unpack
    cached_wheel_filename: pathlib.Path | None = None  # source build path: found in cache
    cached_unpack_dir: pathlib.Path | None = None      # source build path: cached wheel unpack dir
    wheel_filename: pathlib.Path | None = None         # prebuilt path: downloaded wheel
    unpack_dir: pathlib.Path | None = None             # prebuilt path: unpack dir
```

`server.update_wheel_mirror()` is already thread-safe, so the full `_download_prebuilt()` operation (download + create unpack dir + mirror update) can run in the background. `_create_unpack_dir()` already uses `exist_ok=True` (line 1184), so it is already thread-safe. For the source path, `_download_source()` + `_prepare_source()` are fully backgroundable. Note: `_create_unpack_dir()` is **not** called on the source path — `unpack_dir = sdist_root_dir.parent` is derived directly, so the source background callable omits any `_create_unpack_dir()` call.

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

Use a single pool with a minimum of 1 thread for architectural consistency and simplicity:

- Add parameter `num_bg_threads: int = max(1, (os.cpu_count() or 2) // 2)`
- Store effective thread count as `self._num_bg_threads = max(1, num_bg_threads)`
- Always create the pool:
  ```python
  self._bg_pool = concurrent.futures.ThreadPoolExecutor(
      max_workers=self._num_bg_threads, thread_name_prefix="fromager-bg"
  )
  ```

`item.bg_future` is always set for RESOLVE and PREPARE_SOURCE items. The pool is never `None`.

---

## Phase 4: Thread safety — `BootstrapRequirementResolver`

**File:** `src/fromager/bootstrap_requirement_resolver.py`

- Add `self._cache_lock = threading.Lock()` in `__init__` (also add `import threading`)
- Wrap `get_cached_resolution()` body with `with self._cache_lock:`
- Wrap `cache_resolution()` body with `with self._cache_lock:`

A single lock is sufficient — the critical section is a single dict read/write (O(1)).

---

## Phase 5: Refactor `resolve_versions()` to accept explicit `parent_req`

**File:** `src/fromager/bootstrapper.py` (~line 274)

Change the signature from:

```python
def resolve_versions(
    self,
    req: Requirement,
    req_type: RequirementType,
    return_all_versions: bool = False,
) -> list[tuple[str, Version]]:
```

to:

```python
def resolve_versions(
    self,
    req: Requirement,
    req_type: RequirementType,
    parent_req: Requirement | None = None,
    return_all_versions: bool = False,
) -> list[tuple[str, Version]]:
```

Replace the internal `self.why` read:

```python
parent_req = self.why[-1][1] if self.why else None
```

with the explicit `parent_req` parameter (remove the local variable assignment entirely).

Update all existing call sites to pass `parent_req` explicitly:

- `resolve_and_add_top_level()`: `parent_req=None` (top-level, no parent)
- `_phase_resolve()` on main thread: `parent_req=item.why_snapshot[-1][1] if item.why_snapshot else None`
- `_handle_test_mode_failure()`: already reads `self.why[-1][1]` — update to pass from caller context

This refactor removes the `self.why` read from `resolve_versions()`, making the method safe to call from a background thread with a pre-captured `parent_req`. It also correctly handles git URL requirements (the git URL branch is in `resolve_versions()` and is preserved unchanged — only the `parent_req` source changes).

---

## Phase 6: `_get_background_work` method

**File:** `src/fromager/bootstrapper.py` (new method, near `_dispatch_phase`)

```python
def _get_background_work(
    self, item: WorkItem
) -> typing.Callable[[], typing.Any] | None:
```

Returns a zero-argument callable or `None`. **Background callables must be pure: they read fields captured at submission time and must not write to `item` or `self` mutable state.**

**RESOLVE-phase items:**

Capture `parent_req` from `item.why_snapshot` at submission time (not from `self.why`, which is mutable main-thread state):

```python
captured_req = item.req
captured_req_type = item.req_type
captured_parent_req = item.why_snapshot[-1][1] if item.why_snapshot else None
captured_return_all = self.multiple_versions

def _resolve_work() -> list[tuple[str, Version]]:
    return self.resolve_versions(
        req=captured_req,
        req_type=captured_req_type,
        parent_req=captured_parent_req,
        return_all_versions=captured_return_all,
    )
return _resolve_work
```

This correctly handles git URL requirements because `resolve_versions()` contains the full git URL branch.

**PREPARE_SOURCE-phase items:**

- If `item.pbi_pre_built`: return callable that calls the full `_download_prebuilt()` (download wheel + create unpack dir + update mirror) and returns `PreparedSourceData(wheel_filename=<result>, unpack_dir=<result>)`.
- If source build: return callable that calls `_find_cached_wheel()` then (if no cache hit) `_download_source()` + `_prepare_source()`, and returns `PreparedSourceData(...)` with appropriate fields populated. **Do not call `_create_unpack_dir()` in the source path** — `unpack_dir = sdist_root_dir.parent` is derived from the result directly in `_phase_prepare_source`.

**All other phases:** Return `None`.

---

## Phase 7: `_drain_background_pool` method

**File:** `src/fromager/bootstrapper.py` (new method)

```python
def _drain_background_pool(self) -> None:
    self._bg_pool.shutdown(wait=True, cancel_futures=False)
    self._bg_pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=self._num_bg_threads, thread_name_prefix="fromager-bg"
    )
```

Shutdown+recreate is simpler than maintaining a separate list of pending futures. `cancel_futures=False` ensures all submitted tasks complete before rebuilding. Note: exceptions from completed background tasks are stored in the futures but **not raised during drain** — they surface only when the calling code invokes `future.result()` on the item's future. Items with failed futures remain on the stack and their exceptions propagate through `_handle_phase_error` when the item is popped.

---

## Phase 8: Bootstrap loop changes

**File:** `src/fromager/bootstrapper.py`, `bootstrap()` method (~line 413)

After `stack.extend(new_items)`, submit background tasks for newly pushed items **in LIFO processing order** (same order the main loop will pop them):

```python
stack.extend(new_items)
for new_item in reversed(new_items):
    bg_work = self._get_background_work(new_item)
    if bg_work is not None:
        new_item.bg_future = self._bg_pool.submit(bg_work)
```

`reversed(new_items)` submits the item that lands on top of the stack first (the one the main loop reaches soonest). Submitting after `extend` ensures the item is on the stack before the future starts (no race).

---

## Phase 9: `_phase_resolve` changes

**File:** `src/fromager/bootstrapper.py` (~line 1354)

All RESOLVE-phase items always have a background task submitted (via `_resolve_pool`), so `_phase_resolve` unconditionally waits for the future:

```python
assert item.bg_future is not None
resolved_versions = item.bg_future.result()  # blocks if not done; re-raises background exceptions
```

The existing post-resolution logic is **unchanged** — the multiple_versions filtering (calls to `_find_cached_wheel()` for each version) and WorkItem construction all continue to run on the main thread after `bg_future.result()` returns the raw resolution result.

---

## Phase 10: `_phase_prepare_source` changes

**File:** `src/fromager/bootstrapper.py` (~line 1461)

At the top of the method, wait for the background result if present:

```python
prepared: PreparedSourceData | None = None
if item.bg_future is not None:
    prepared = item.bg_future.result()  # blocks if not done; re-raises background exceptions
```

Then use `prepared` to skip already-done I/O:

- If prebuilt and `prepared` is set with `wheel_filename` + `unpack_dir`: skip the full `_download_prebuilt()` call.
- If source and `prepared.sdist_root_dir` is set: skip `_download_source()` + `_prepare_source()`, use result directly. Derive `unpack_dir = prepared.sdist_root_dir.parent` (no `_create_unpack_dir()` needed on the source path).
- If source and `prepared.cached_wheel_filename` is set: use cached wheel path from background result.
- If `prepared` is None (background disabled or phase reached without a bg task): existing logic unchanged.

`_create_build_env()` (line 1525) remains on the main thread regardless — it operates in a directory unique per package+version (thread-safe), but keeping it on the main thread is simpler and correct.

Exceptions raised in the background task surface via `future.result()`, propagate through `_dispatch_phase`, and are caught by the existing `_handle_phase_error` machinery — correct behavior.

---

## Phase 11: `_phase_build` exclusive-build drain

**File:** `src/fromager/bootstrapper.py` (~line 1597)

At the top of `_phase_build`:

```python
pbi = self.ctx.package_build_info(item.req)
if pbi.exclusive_build:
    logger.info("%s requires exclusive build, draining background pool", item.req)
    self._drain_background_pool()
```

`package_build_info()` reads package configuration (no network I/O), so adding it at the top of `_phase_build` does not add latency to the hot path. Placed before any build work begins. After the exclusive build completes, the pool (now recreated empty) continues accepting new submissions.

---

## Phase 12: `finalize()` pool shutdown

**File:** `src/fromager/bootstrapper.py`, `finalize()` (~line 1852)

At the start of `finalize()`:

```python
self._bg_pool.shutdown(wait=True, cancel_futures=False)
self._bg_pool = None
```

The pool is created in `__init__` and lives across all `bootstrap()` calls; `finalize()` is the natural cleanup point.

---

## Phase 13: CLI option

**File:** `src/fromager/commands/bootstrap.py` (~line 113)

Add Click option before `@click.argument("toplevel", ...)`:

```python
@click.option(
    "--bg-threads",
    "num_bg_threads",
    type=click.IntRange(min=0),
    default=max(1, (os.cpu_count() or 2) // 2),
    show_default=True,
    help="Number of background threads for parallel I/O pre-fetching and resolution. Minimum 1 thread is always used.",
)
```

Add `num_bg_threads: int` to function signature. Pass `num_bg_threads=num_bg_threads` to `Bootstrapper(...)`.

---

## Files to modify

| File | Changes |
| -- | -- |
| `src/fromager/bootstrapper.py` | New `PreparedSourceData`, `WorkItem.bg_future`, `Bootstrapper.__init__` (single pool, min 1 thread), refactor `resolve_versions()` to accept `parent_req`, new `_get_background_work`, new `_drain_background_pool`, bootstrap loop, `_phase_resolve`, `_phase_prepare_source`, `_phase_build`, `finalize()` |
| `src/fromager/bootstrap_requirement_resolver.py` | `threading.Lock` for `_resolved_requirements` cache |
| `src/fromager/commands/bootstrap.py` | `--bg-threads` CLI option |

No new files. `server.update_wheel_mirror()` is already thread-safe. `_create_unpack_dir()` already uses `exist_ok=True` (already thread-safe). No changes to `sources.py` expected — different packages use different source directories, so concurrent background tasks for different packages won't collide. Background callables must not mutate `WorkItem` fields directly — all results are returned as `PreparedSourceData` values.

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

- `TestResolveVersionsWithParentReq` — verifies that the refactored `resolve_versions()` passes `parent_req` to `_resolver.resolve()` rather than reading `self.why`; verifies the git URL branch is unaffected by the signature change
- `TestGetBackgroundWork` — returns `None` for non-I/O phases; returns callable for RESOLVE and PREPARE_SOURCE; RESOLVE callable captures `parent_req` from `why_snapshot` not `self.why`; source PREPARE_SOURCE callable does not call `_create_unpack_dir()`; background callables do not write to `item`
- `TestPhasePrepareSourceWithBgFuture` — uses background result to skip download/unpack; source path derives `unpack_dir` from `sdist_root_dir.parent` (no separate field); exception in background propagates correctly; falls back gracefully when `bg_future` is None
- `TestDrainBackgroundPool` — no-op when `_bg_pool` is None; pool is recreated after drain; all futures complete before return; exceptions in completed futures are not raised during drain
- `TestExclusiveBuildBarrier` — `_phase_build` calls drain for `exclusive_build=True`; does not call drain for `exclusive_build=False`
