# Unique wheel file names with a `wheel_build_tag` hook

- Author: Christian Heimes
- Created: 2026-04-16
- Status: Open
- GitHub issue: [#1059](https://github.com/python-wheel-build/fromager/issues/1059)

## What

This enhancement proposes a new stevedore hook point, `wheel_build_tag`, in
the existing `fromager.hooks` namespace. The hook lets downstream plugin
packages inject custom suffixes into the
[wheel build tag](https://packaging.python.org/en/latest/specifications/binary-distribution-format/),
producing unique wheel file names that encode platform, accelerator stack,
and dependency ABI information.

## Why

Fromager-built wheels are platform-specific and may depend on:

- **OS / distribution version**, e.g. Fedora 43, RHEL 9.6, RHEL 10.1
- **AI accelerator stack**, e.g. CUDA 13.1 vs CUDA 12.9, ROCm 7.1
- **Torch ABI**, which is unstable across versions; a wheel compiled for
  Torch 2.10.0 may have a different ABI than one compiled for Torch 2.11.0

Currently, wheel filenames carry none of this information. A rebuild for a
new Torch version does not produce a new filename, making it difficult to:

1. Invalidate caches when the underlying platform or dependency stack changes.
2. Distinguish wheels built for different accelerator stacks or OS versions.
3. Replace outdated wheels with correctly-targeted rebuilds.
4. Share wheels between indexes. Downstream maintains a separate index for
   each accelerator version, but only a couple of dozen packages out of over
   1,200 are CUDA/ROCm/Torch-specific. Wheels like `pillow` or `fromager`
   are identical across accelerator indexes and could be shared if their
   filenames clearly indicate they have no accelerator dependency. Sharing is
   out of scope for this proposal but is a possibility for future
   improvements in downstream.

## Goals

- introduce a `wheel_build_tag` hook point in the `fromager.hooks` stevedore
  namespace
- allow hooks to contribute ordered suffix segments to the wheel build tag
- produce unique, deterministic wheel file names that reflect the build
  environment

## Non-goals

- Filtering or selecting wheels by build tag at install time. `pip install`
  and `uv pip install` only use the build tag for sorting, not for filtering.
- Sharing wheels across indexes. While unique file names enable this in
  principle, the mechanics of cross-index sharing are out of scope.
- Accessing wheel content, the build environment, or ELF dependency info from
  within the hook. The hook must work identically whether a wheel is freshly
  built or retrieved from cache.
- Validation of annotations such as "depends on libtorch". A validation
  system for `build_wheel` may be added in the future.
- Per-package plugin hooks (`overrides.find_and_invoke()`). A per-package
  override can be added later when the need arises.

## How

### Wheel spec background

The wheel filename format is:

```
{distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
```

The build tag is optional, must start with a digit, and must not contain `-`.
It is parsed as `tuple[int, str]`. Fromager already fills the `int` part from
variant + package changelog and sets the `str` suffix to `""`. The build tag
is also stored in the `{name}-{version}.dist-info/WHEEL` metadata file and
shown in `pip list` output.

This proposal extends that suffix with hook-provided segments (e.g.
`_el9.6_rocm7.1_torch2.10.0`).

### Hook signature

```python
def build_tag_hook(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    wheel_tags: frozenset[Tag],
) -> typing.Sequence[tuple[int, str]]:
    ...
```

Each registered hook returns `typing.Sequence[tuple[int, str]]`, a sequence
of (sort-order, suffix) pairs. This allows a single hook to contribute
multiple suffix segments (e.g. both an OS tag and an accelerator tag). The
runner collects all pairs from all hooks, sorts them in ascending order, and
returns the suffix parts as a sequence. Neither `sort-order` nor `suffix`
have to be unique. The first appearance of a `suffix` is used. Suffixes are
are joined with `_` and appended to the existing build tag.

`suffix` must only contain alphanumeric ASCII characters or dot
(`[a-zA-Z0-9.]`). When a hook returns any other character or raises an
exception, the build fails.

Build tag hooks are registered for `fromager.hooks` entry point and name
`wheel_build_tag`.

### Example hook

```python
def example_hook(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    wheel_tags: frozenset[Tag],
) -> typing.Sequence[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    platlib = any(tag.platform != "any" for tag in wheel_tags)
    if platlib:
        # fc43, el9.6, ...
        result.append((1, get_distro_tag()))
    pbi = ctx.package_build_info(req)

    # example how to use anntoations and ctx.variant for custom flags
    if pbi.annotations.get("example.accelerator-specific") == "true":
        # cpu, cuda13.0, ...
        if ctx.variant.startswith("cpu"):
            result.append((2, "cpu"))
        elif ctx.variant.startswith("cuda"):
            cv = Version(os.environ["CUDA_VERSION"])
            result.append((2, f"cuda{cv.major}.{cv.minor}"))
        else:
            raise NotImplementedError(ctx.variant)
    return result
```

```python
@functools.cache
def get_distro_tag() -> str:
    info = platform.freedesktop_os_release()
    ids = [info["ID"]]  # always defined
    if "ID_LIKE" in info:  # ids in precedence order
        ids.extend(info["ID_LIKE"].split())
    version_id = info.get("VERSION_ID", "")
    for ident in ids:
        if ident == "rhel":  # RHEL and CentOS
            return f"el{version_id}"
        elif ident == "fedora":
            return f"fc{version_id}"
    # other distros
    return f"{ids[0]}{version_id}".replace("_", "").replace("-", "")
```

Registration:

```toml
[project.entry-points."fromager.hooks"]
wheel_build_tag = "mypackage.hooks:example_hook"
```

### What hooks can access

- **`ctx` + `req`**: for `ctx.variant` and package configuration like annotations
- **`wheel_tags`**: detect whether a wheel is purelib or platlib
  (platform/arch-specific).

Hooks can also use other information like **`os.environ`** or the
**`platform`** stdlib module. They should only use information that
is immutable and identifies the build context, e.g.
**`platform.freedesktop_os_release()`** to read distribution name and
version from `/etc/os-release`.

### What hooks cannot access

The hook **does not** have access to wheel content, the `build_env`, or
ELF dependency info. While this information exists during the build, it is
not available when wheels are retrieved from cache servers or local cache. The
hook must work identically in both paths.

### Examples

#### RHEL 9.6, ROCm 7.1, Torch 2.10.0

| Wheel | Build tag |
| -- | -- |
| `flash_attn-2.8.3-8_el9.6_rocm7.1_torch2.10.0-cp312-cp312-linux_x86_64.whl` | `8_el9.6_rocm7.1_torch2.10.0` |
| `torch-2.10.0-7_el9.6_rocm7.1-cp312-cp312-linux_x86_64.whl` | `7_el9.6_rocm7.1` |
| `pillow-12.2.0-2_el9.6-cp312-cp312-linux_x86_64.whl` | `2_el9.6` |
| `fromager-0.79.0-2-py3-none-any.whl` | `2` (pure-python, no suffix) |

#### Fedora 43, CUDA 13.0, Torch 2.9.1

| Wheel | Build tag |
| -- | -- |
| `flash_attn-2.8.3-8_fc43_cuda13.0_torch2.9.1-cp312-cp312-linux_x86_64.whl` | `8_fc43_cuda13.0_torch2.9.1` |
| `torch-2.9.1-8_fc43_cuda13.0-cp312-cp312-linux_x86_64.whl` | `8_fc43_cuda13.0` |
| `pillow-12.2.0-2_fc43-cp312-cp312-linux_x86_64.whl` | `2_fc43` |
| `fromager-0.79.0-2-py3-none-any.whl` | `2` (pure-python, no suffix) |

Note how pure-python wheels (`py3-none-any`) receive no suffix, while
platlib wheels get progressively more specific tags based on their actual
dependencies.

## Limitations

The current wheel standard does not support multiple accelerator variants in
a single package index. A single index cannot contain both CUDA and ROCm
builds of the same package because `pip install` and `uv pip install` only
use the build tag for sorting, not for filtering. An index with both CUDA
and ROCm wheels would result in the installer picking whichever has the
highest build tag, not the correct accelerator.

The upcoming [Wheel.Next](https://wheelnext.dev/) initiative and
[PEP 817](https://peps.python.org/pep-0817/) /
[PEP 825](https://peps.python.org/pep-0825/) aim to address this by
introducing wheel variants, which will enable CUDA and ROCm wheels to
coexist in the same index. Logic for Torch and CUDA/ROCm dependency
selection in this proposal may be reused by wheel variants when the new
standard becomes available.
