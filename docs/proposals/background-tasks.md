# Plan: Background Task Parallelization for Bootstrapper

## Context

The bootstrap process builds packages via a serial iterative LIFO stack. Version resolution (PyPI network calls) and source preparation (download + unpack) are pure I/O that block the main loop while the stack sits idle. By submitting these operations to a background thread pool as items are pushed onto the stack, we can overlap I/O with the main thread's serial processing, reducing total bootstrap time without changing build order.

The `exclusive_build` flag already exists in `PackageBuildInfo` and is the signal to drain the pool before an exclusive build starts.

### Design Principles

- Background callables are **module-level functions** (not inner closures). This mechanically prevents accidental access to mutable `Bootstrapper` instance state (`self.why`, `self._seen_requirements`, etc.) from background threads.
- All state needed by a background function is captured as explicit arguments via `functools.partial` at submission time.
- `ctx` (a `WorkContext`) and `cache_wheel_server_url` are effectively read-only after construction and safe to pass to background functions.

---

## Phase 1: `PreparedSourceData` dataclass

**File:** `src/fromager/bootstrapper.py` (after `SourceBuildResult`)

New dataclass carrying the result of background I/O pre-fetching for `PREPARE_SOURCE` back to the main thread. Exactly one of (`sdist_root_dir`, `wheel_filename`) will be set:

```python
@dataclasses.dataclass
class PreparedSourceData:
    """Result of background I/O pre-fetching returned to the main thread.

    Exactly one of (sdist_root_dir, wheel_filename) will be set depending
    on whether this is a source or prebuilt result.
    """
    # Source path: set after download+unpack OR cache hit
    sdist_root_dir: pathlib.Path | None = None
    # Source path: set when the result came from the wheel cache
    cached_wheel_filename: pathlib.Path | None = None
    # Prebuilt path: downloaded wheel file
    wheel_filename: pathlib.Path | None = None
    # Prebuilt path: unpack directory (created by mkdir)
    unpack_dir: pathlib.Path | None = None
```

`unpack_dir` for the source path is always derived as `sdist_root_dir.parent` in the main-thread phase handler — it is never stored in `PreparedSourceData`.

---

## Phase 2: `WorkItem` changes

**File:** `src/fromager/bootstrapper.py` (`WorkItem` dataclass)

Add one field:

```python
bg_future: concurrent.futures.Future[typing.Any] | None = dataclasses.field(
    default=None, compare=False, repr=False
)
```

`compare=False, repr=False` avoids interference with dataclass ordering and logging.

---

## Phase 3: `Bootstrapper.__init__` changes

**File:** `src/fromager/bootstrapper.py`

- Add parameter `num_bg_threads: int = max(1, (os.cpu_count() or 2) // 2)`
- Store effective thread count as `self._num_bg_threads = max(1, num_bg_threads)`
- Always create the pool:
  ```python
  self._bg_pool = concurrent.futures.ThreadPoolExecutor(
      max_workers=self._num_bg_threads, thread_name_prefix="fromager-bg"
  )
  ```

The pool is always created; `item.bg_future` is always set for RESOLVE and PREPARE_SOURCE items.

---

## Phase 4: Thread safety — `BootstrapRequirementResolver`

**File:** `src/fromager/bootstrap_requirement_resolver.py`

- Add `import threading`
- Add `self._cache_lock = threading.Lock()` in `__init__`
- Wrap `get_cached_resolution()` body with `with self._cache_lock:`
- Wrap `cache_resolution()` body with `with self._cache_lock:`

A single lock is sufficient — the critical section is a single dict read/write (O(1)). Concurrent threads calling `resolve()` for the same package produce identical deterministic results; a second cache write with the same value is benign.

---

## Phase 5: Refactor `resolve_versions()` to accept explicit `parent_req`

**File:** `src/fromager/bootstrapper.py`

Change the signature to:

```python
def resolve_versions(
    self,
    req: Requirement,
    req_type: RequirementType,
    parent_req: Requirement | None = None,
    return_all_versions: bool = False,
) -> list[tuple[str, Version]]:
```

Replace the internal `self.why` read with the explicit `parent_req` parameter. This makes the method callable from background threads without accessing mutable `self.why`.

Update all call sites to pass `parent_req` explicitly:

- `resolve_and_add_top_level()`: `parent_req=None`
- `_get_background_work()`: `parent_req=item.why_snapshot[-1][1] if item.why_snapshot else None`

The git URL branch in `resolve_versions()` is preserved unchanged — only the `parent_req` source changes.

---

## Phase 6: Module-level background functions and `_get_background_work`

**File:** `src/fromager/bootstrapper.py` (module-level, before `Bootstrapper` class)

### Standalone helper functions

These extract the I/O logic from Bootstrapper instance methods, accepting all needed state as explicit parameters:

```python
def _create_unpack_dir_standalone(work_dir, req, resolved_version) -> pathlib.Path
def _unpack_metadata_from_wheel_standalone(work_dir, req, resolved_version, wheel_filename) -> pathlib.Path | None
def _look_for_existing_wheel_standalone(ctx, req, resolved_version, search_in) -> tuple[...]
def _download_wheel_from_cache_standalone(ctx, cache_wheel_server_url, req, resolved_version) -> tuple[...]
def _find_cached_wheel_standalone(ctx, cache_wheel_server_url, req, resolved_version) -> tuple[...]
```

The corresponding Bootstrapper instance methods delegate to these standalone functions.

### Background callable functions

```python
def _bg_resolve(
    bg_resolver: BootstrapRequirementResolver,
    req: Requirement,
    req_type: RequirementType,
    parent_req: Requirement | None,
    return_all_versions: bool,
) -> list[tuple[str, Version]]:
    """Background-safe resolution: no Bootstrapper state accessed."""
    return bg_resolver.resolve(req=req, req_type=req_type,
                               parent_req=parent_req,
                               return_all_versions=return_all_versions)


def _bg_prepare_source(
    ctx: context.WorkContext,
    cache_wheel_server_url: str | None,
    req: Requirement,
    resolved_version: Version,
    source_url: str,
) -> PreparedSourceData:
    """Background-safe source download+unpack: no Bootstrapper state accessed."""
    cached_wheel, unpacked = _find_cached_wheel_standalone(ctx, cache_wheel_server_url, req, resolved_version)
    if unpacked is not None:
        return PreparedSourceData(sdist_root_dir=unpacked / unpacked.stem,
                                  cached_wheel_filename=cached_wheel)
    source_filename = sources.download_source(ctx=ctx, req=req,
                                               version=resolved_version,
                                               download_url=source_url)
    sdist_root_dir = sources.prepare_source(ctx=ctx, req=req,
                                             source_filename=source_filename,
                                             version=resolved_version)
    return PreparedSourceData(sdist_root_dir=sdist_root_dir)


def _bg_prepare_prebuilt(
    ctx: context.WorkContext,
    req: Requirement,
    req_type: RequirementType,
    resolved_version: Version,
    wheel_url: str,
) -> PreparedSourceData:
    """Background-safe prebuilt download: no Bootstrapper state accessed."""
    wheel_filename = wheels.download_wheel(req, wheel_url, ctx.wheels_prebuilt)
    unpack_dir = ctx.work_dir / f"{req.name}-{resolved_version}"
    unpack_dir.mkdir(parents=True, exist_ok=True)
    server.update_wheel_mirror(ctx)
    return PreparedSourceData(wheel_filename=wheel_filename, unpack_dir=unpack_dir)
```

### `_get_background_work` method (on `Bootstrapper`)

Uses `functools.partial` to bind module-level functions to captured values — the returned callable cannot access `self`:

```python
def _get_background_work(self, item: WorkItem) -> Callable[[], Any] | None:
    if item.phase == BootstrapPhase.RESOLVE:
        return functools.partial(
            _bg_resolve, self._resolver, item.req, item.req_type,
            item.why_snapshot[-1][1] if item.why_snapshot else None,
            self.multiple_versions,
        )
    if item.phase == BootstrapPhase.PREPARE_SOURCE:
        if item.pbi_pre_built:
            return functools.partial(_bg_prepare_prebuilt, self.ctx, item.req,
                                     item.req_type, item.resolved_version, item.source_url)
        return functools.partial(_bg_prepare_source, self.ctx,
                                 self.cache_wheel_server_url, item.req,
                                 item.resolved_version, item.source_url)
    return None
```

---

## Phase 7: `_drain_background_pool` method

**File:** `src/fromager/bootstrapper.py`

```python
def _drain_background_pool(self) -> None:
    if self._bg_pool is not None:
        self._bg_pool.shutdown(wait=True, cancel_futures=False)
        self._bg_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=self._num_bg_threads, thread_name_prefix="fromager-bg"
        )
```

`cancel_futures=False` ensures all submitted tasks complete before rebuilding (exclusive-build barrier must drain all pre-fetched I/O). Exceptions from completed background tasks are stored in their futures and surface via `future.result()` when the item is popped from the stack.

---

## Phase 8: `_push_items` helper and bootstrap loop

**File:** `src/fromager/bootstrapper.py`

Replace all `stack.extend(items)` calls with a `_push_items` helper that pushes and submits background tasks together:

```python
def _push_items(self, stack: list[WorkItem], items: list[WorkItem]) -> None:
    """Push items onto the stack and submit background tasks in LIFO order."""
    stack.extend(items)
    if self._bg_pool is not None:
        for item in reversed(items):  # submit top-of-stack first
            bg_work = self._get_background_work(item)
            if bg_work is not None:
                item.bg_future = self._bg_pool.submit(bg_work)
```

This guarantees every RESOLVE and PREPARE_SOURCE item has `bg_future` set, including the initial item created in `bootstrap()`.

**Initial item in `bootstrap()`:**

```python
initial_item = WorkItem(req=req, req_type=req_type, phase=BootstrapPhase.RESOLVE,
                        why_snapshot=list(self.why), parent=parent)
stack: list[WorkItem] = []
self._push_items(stack, [initial_item])
```

**Main loop body:**

```python
self._push_items(stack, new_items)
```

---

## Phase 9: `_phase_resolve` changes

All RESOLVE-phase items are guaranteed to have `bg_future` set (via `_push_items`), so `_phase_resolve` unconditionally asserts and waits:

```python
assert item.bg_future is not None
resolved_versions = item.bg_future.result()  # blocks if not done; re-raises background exceptions
```

The existing post-resolution logic (multiple_versions filtering, WorkItem construction) continues unchanged on the main thread.

---

## Phase 10: `_phase_prepare_source` changes

At the top of the method, wait for the background result:

```python
prepared: PreparedSourceData | None = None
if item.bg_future is not None:
    prepared = item.bg_future.result()  # blocks if not done; re-raises background exceptions
```

Then use `prepared` to skip already-done I/O:

- If prebuilt and `prepared.wheel_filename` is set: use directly, skip `_download_prebuilt()`.
- If source and `prepared.sdist_root_dir` is set: use directly, skip download+prepare; set `item.cached_wheel_filename = prepared.cached_wheel_filename`.
- Fallback when `prepared` is None: existing inline I/O logic unchanged.

`_create_build_env()` remains on the main thread (it's fast and operates in a unique directory per package).

---

## Phase 11: `_phase_build` exclusive-build drain

At the top of `_phase_build`:

```python
pbi = self.ctx.package_build_info(item.req)
if pbi.exclusive_build:
    logger.info("%s requires exclusive build, draining background pool", item.req)
    self._drain_background_pool()
```

After the exclusive build completes, the recreated pool accepts new submissions.

---

## Phase 12: `finalize()` pool shutdown

At the start of `finalize()`:

```python
if self._bg_pool is not None:
    self._bg_pool.shutdown(wait=True, cancel_futures=True)
    self._bg_pool = None
```

`cancel_futures=True` cancels pending-but-not-started futures immediately (their results will never be used), while already-running futures still complete. This avoids blocking on the error-abort path.

---

## Phase 13: CLI option

**File:** `src/fromager/commands/bootstrap.py`

```python
@click.option(
    "--bg-threads",
    "num_bg_threads",
    type=click.IntRange(min=1),
    default=max(1, (os.cpu_count() or 2) // 2),
    show_default=True,
    help="Number of background threads for parallel I/O pre-fetching (min 1).",
)
```

`IntRange(min=1)` enforces a meaningful minimum; 0 threads is not a valid configuration given the design always creates a pool.

---

## Files modified

| File | Changes |
| -- | -- |
| `src/fromager/bootstrapper.py` | New `PreparedSourceData`; `WorkItem.bg_future`; `Bootstrapper.__init__` (pool); refactor `resolve_versions()` (`parent_req`); standalone helper functions; `_push_items`, `_get_background_work`, `_drain_background_pool`; updated `bootstrap()`, `_phase_resolve`, `_phase_prepare_source`, `_phase_build`, `finalize()` |
| `src/fromager/bootstrap_requirement_resolver.py` | `threading.Lock` for `_resolved_requirements` cache |
| `src/fromager/commands/bootstrap.py` | `--bg-threads` CLI option |

---

## Verification

```bash
# Type check changed files
hatch run mypy:check src/fromager/bootstrapper.py \
    src/fromager/bootstrap_requirement_resolver.py \
    src/fromager/commands/bootstrap.py

# Run targeted tests
hatch run test:test tests/test_bootstrapper.py tests/test_bootstrapper_iterative.py

# Lint
hatch run lint:fix src/fromager/bootstrapper.py \
    src/fromager/bootstrap_requirement_resolver.py \
    src/fromager/commands/bootstrap.py
```

New tests to add to `tests/test_bootstrapper_iterative.py`:

- `TestResolveVersionsWithParentReq` — verifies `resolve_versions()` passes `parent_req` explicitly; git URL branch unaffected
- `TestPushItems` — initial item gets `bg_future` set; items from phase handlers get `bg_future` set; non-I/O-phase items get `bg_future=None`; submits in LIFO order
- `TestGetBackgroundWork` — returns `None` for non-I/O phases; returns `functools.partial` wrapping module-level functions for RESOLVE and PREPARE_SOURCE; callable does not reference `self`
- `TestBgResolve` — unit test `_bg_resolve` directly (no Bootstrapper needed)
- `TestBgPrepareSource` / `TestBgPreparePrebuilt` — unit test module-level functions directly
- `TestPhaseResolveWithBgFuture` — future result used when set; exception propagates
- `TestPhasePrepareSourceWithBgFuture` — background result used; exception propagates; fallback when None; `item.cached_wheel_filename` set correctly
- `TestDrainBackgroundPool` — all futures complete before return; pool is recreated
- `TestExclusiveBuildBarrier` — drain called for `exclusive_build=True`, not for `False`
