# Build isolation for sandboxing build backends

- Author: Pavan Kalyan Reddy Cherupally
- Created: 2026-04-21
- Status: Open
- Issue: [#1019](https://github.com/python-wheel-build/fromager/issues/1019)

## What

A `--build-isolation` flag that sandboxes PEP 517 build backend
subprocesses (`build_sdist`, `build_wheel`) so they cannot read
credentials, access the network, or interfere with the host system.

## Why

Fromager executes upstream-controlled code (setup.py, build backends)
during wheel builds. A compromised or malicious package can:

- Read credential files like `$HOME/.netrc` and exfiltrate tokens
- Reach the network to upload stolen data or download payloads
- Signal or inspect other processes via `/proc` or shared IPC
- Interfere with parallel builds through shared `/tmp`
- Leave persistent backdoors: `.pth` files that run on every Python
  startup, shell profile entries that run on every login, or
  background daemons that survive the build

The existing `--network-isolation` flag blocks network access but does
not protect against credential theft, process/IPC visibility, or
persistent backdoors.

Build isolation wraps each build backend invocation in a sandbox that
combines file-level credential protection with OS-level namespace
isolation. Only the PEP 517 hook calls are sandboxed; download,
installation, and upload steps run normally.

## Goals

- A `--build-isolation/--no-build-isolation` CLI flag (default off)
  that supersedes `--network-isolation` for build steps
- Credential protection: build processes cannot read `.netrc` or
  other root-owned credential files
- Network isolation: no routing in the build namespace
- Process and IPC isolation: build cannot see other processes or
  access shared memory and semaphores
- Persistence protection: build cannot drop `.pth` backdoors, modify
  shell profiles, or leave background daemons running after the build
- Works in unprivileged containers (Podman/Docker) without
  `--privileged` or `--cap-add SYS_ADMIN`

## Non-goals

- **Mount namespace isolation.** Breaks `pyproject_hooks` IPC, which
  exchanges `input.json`/`output.json` through `/tmp`.
- **macOS / Windows support.** Linux-only; flag is unavailable on
  other platforms.

## How

Build isolation combines an ephemeral Unix user with Linux namespace
isolation. Before each build, a short-lived system user (`fmr_<random>`)
is created with `useradd` and removed on exit via `trap EXIT`. The user
has no home directory and no login shell, so it cannot read root-owned
credential files like `.netrc` (mode 600). After dropping to the
ephemeral user with `setpriv`, the script enters new namespaces with
`unshare`:

| Namespace | Flag | Purpose |
| -- | -- | -- |
| Network | `--net` | No routing; blocks all network access |
| PID | `--pid --fork` | Build sees only its own processes |
| IPC | `--ipc` | Isolated shared memory and semaphores |
| UTS | `--uts` | Separate hostname |

`--map-root-user` maps the ephemeral user to UID 0 inside the
namespace, giving it enough privilege to bring up the loopback
interface without requiring real root.

### Order of operations

```
useradd fmr_<random>          # create ephemeral user (outside namespace)
  └─ setpriv --reuid --regid  # drop to ephemeral user
       └─ unshare --uts --net --pid --ipc --fork --map-root-user
            ├─ ip link set lo up
            ├─ hostname localhost
            └─ exec <build command>
userdel fmr_<random>          # cleanup (trap EXIT)
```

The user is created before entering the namespace because `useradd`
needs access to `/etc/passwd` and `/etc/shadow` on the real
filesystem. `setpriv` drops privileges before `unshare` so the UID
switch happens outside the namespace where the real UID is mapped.

### Integration points

- `__main__.py`: `--build-isolation/--no-build-isolation` CLI flag,
  detected at import time (same pattern as network isolation)
- `context.py`: new `build_isolation: bool` field on `WorkContext`
- `build_environment.py`: threads `build_isolation` through `run()`;
  `install()` passes `False` (needs local PyPI mirror access)
- `dependencies.py`: passes `ctx.build_isolation` to build hooks
- `external_commands.py`: prepends isolation script, sets
  `FROMAGER_BUILD_DIR` and `CARGO_NET_OFFLINE=true`

## Examples

```bash
fromager --build-isolation bootstrap -r requirements.txt
```

## Findings

A proof-of-concept package
([build-attack-test](https://github.com/pavank63/build-attack-test))
was used to validate the attack surface. It runs security probes from
`setup.py` during `build_sdist` / `build_wheel` to test what a
malicious build backend can access. Testing was performed with
`--network-isolation` enabled.

### Results without build isolation

| Attack vector | Result | Risk |
| -- | -- | -- |
| Credential file access (`.netrc`) | **Vulnerable** | Build can read credential files containing auth tokens |
| Network access | Blocked | Already mitigated by `--network-isolation` |
| Process visibility (PID) | **Vulnerable** | Build can see all running processes and their arguments |
| IPC (shared memory, semaphores) | **Vulnerable** | Build can access shared memory segments from other processes |
| Hostname | **Vulnerable** | Real hostname visible, leaks build infrastructure identity |
| Shared cache/config access | **Vulnerable** | Build can read/write ccache, cargo caches, and package settings |
| Persistent backdoors (.pth, shell profiles, pip.conf, daemons) | **Vulnerable** | Build can leave files or processes that survive the build and affect subsequent builds |

### Supply-chain risk

Network isolation alone is insufficient. A build can steal
credentials from `.netrc` and embed them in the built wheel — the
credentials leave the build system when the wheel is distributed,
bypassing network controls entirely.

The persistence attacks are especially dangerous because fromager
builds many packages sequentially in the same environment. A single
malicious package built early in the bootstrap can compromise every
package built after it through `.pth` files that run on every Python
startup, a poisoned `pip.conf` that redirects dependency installs, a
poisoned compiler cache that injects code into later builds, or a
background daemon that modifies source before the next build starts.

Build isolation breaks this chain. Each build runs as a separate
ephemeral user in its own PID, IPC, and network namespace. Parallel
builds each get their own ephemeral user and cannot interfere with
each other.

### Remaining gaps

Build cache poisoning and package settings access are **not fully
addressed** by this proposal, as the ephemeral user still needs
write access to the build directory. Addressing these would require
mount namespace isolation, which is incompatible with the current
`pyproject_hooks` IPC mechanism (see Non-goals).
