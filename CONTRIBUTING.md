# Contributing to Fromager

Fromager thrives on practical, well-tested contributions. This guide summarizes how to set up a workspace, follow our standards, and submit polished changes. Skim it once, keep it handy, and refer back whenever you are unsure.

## Table of Contents

- [Quick Start](#quick-start)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Commit Guidelines](#commit-guidelines)
- [Before Submitting](#before-submitting)
- [Design Patterns Used in Fromager](#design-patterns-used-in-fromager)
- [Quick Reference](#quick-reference)
- [Getting Help](#getting-help)
- [Resources](#resources)

---

## Quick Start

### Prerequisites

- Python 3.11 or newer
- `hatch` for environment and task management

### Initial Setup

```bash
git clone https://github.com/python-wheel-build/fromager.git
cd fromager
hatch env create
```

### Daily Workflow

```bash
# 1. Start from main
git checkout main
git pull --ff-only

# 2. Create a focused branch
git checkout -b feat/<short-description>

# 3. Make changes and keep them formatted
hatch run lint:fix
hatch run test:test
hatch run mypy:check
hatch run lint:check

# 4. Commit using Conventional Commits
git commit -m "feat(scope): short summary"
```

---

## Coding Standards

### Type Annotations

- Every function (including tests) must annotate all parameters and return values.
- Use modern `X | None` syntax instead of `Optional[X]`.
- Prefer precise collection types (`list[str]`, `dict[str, int]`, etc.).

```python
def process(data: str | None, count: int = 0) -> dict[str, int]:
    """Process the input and return aggregate counts."""
    return {}
```

### Code Quality and Formatting

- Ruff enforces both formatting and linting.
- Keep lines ≤ 88 characters, remove trailing whitespace, and end every file with a single newline.
- See [Quick Reference](#quick-reference) for formatting commands.

### Import Organization

1. Future imports.
2. Standard library (alphabetical).
3. Third-party packages (alphabetical).
4. Local imports.
5. Type-only imports guarded by `typing.TYPE_CHECKING`.

```python
from __future__ import annotations

import logging
import pathlib
import typing

from packaging.requirements import Requirement

from . import constraints

if typing.TYPE_CHECKING:
    from . import context

logger = logging.getLogger(__name__)
```

### Documentation Expectations

- Add a module docstring describing purpose and high-level behavior.
- Public functions and classes require docstrings that cover arguments, return values, and noteworthy behavior.
- Keep prose short and imperative; explain "why" decisions when the code itself cannot.

```python
def retry_on_exception(
    exceptions: tuple[type[Exception], ...],
    max_attempts: int = 5,
) -> typing.Callable:
    """Retry decorated call on the provided exception types.

    Args:
        exceptions: Exception types that trigger a retry.
        max_attempts: Maximum number of attempts.

    Returns:
        Decorator function.
    """
    ...
```

### Commenting Guidelines

- Write self-explanatory code; reserve comments for non-obvious intent or domain context.
- Capture reasoning, invariants, or unexpected trade-offs—never repeat the code literally.

```python
# Bad - comment just repeats the code
x = x + 1  # increment x

# Good - clear variable name makes the comment unnecessary
total_attempts += 1

# Good - comment explains the reasoning behind the approach
# Exponential backoff avoids thundering herd when many jobs retry at once.
wait_time = min(2**attempt + random.uniform(0, 1), max_backoff)
```

### Logging

- Use a module-level logger and the appropriate log level for the situation.
- When processing per-requirement work, wrap nested calls in `req_ctxvar_context()` so log records automatically include the package (and optional version). This keeps CLI logs searchable even when work runs in parallel.

```python
logger = logging.getLogger(__name__)

def sync_artifacts() -> None:
    logger.info("Starting artifact sync")
    logger.debug("Artifacts queued: %s", pending_jobs)

with req_ctxvar_context(req, version):
    logger.info("Resolving build dependencies")
```

### Error Handling

- Raise specific exceptions with actionable messages.
- Chain exceptions (`raise ... from e`) so stack traces stay informative.

```python
try:
    result = process_data(file_path)
except FileNotFoundError as err:
    raise ValueError(f"Cannot load config at {file_path}") from err
```

---

## Testing

### Structure

- Place tests under `tests/`.
- Name files `test_<module>.py` and functions `test_<behavior>()`.
- Keep tests small: arrange, act, assert.

```python
def test_load_config(tmp_path: pathlib.Path) -> None:
    """Verify config loads with expected values."""
    # Arrange
    config_file = tmp_path / "config.txt"
    config_file.write_text("setting=value\n")
    # Act
    result = load_config(config_file)
    # Assert
    assert result["setting"] == "value"
```

### Useful Commands

```bash
hatch run test:test                              # Full suite
hatch run test:test tests/test_context.py        # Specific file
hatch run test:test --log-level DEBUG            # Verbose output
hatch run test:coverage-report                   # Coverage summary
```

---

## Commit Guidelines

Fromager follows [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

```
<type>(<scope>): <short summary>

<body explaining what + why>

<footer for metadata>
```

### Common Types

- `feat`: new functionality
- `fix`: bug fix
- `docs`: documentation only
- `test`: tests only
- `refactor`: behavioral no-op refactor
- `perf`: performance improvement
- `chore`: tooling or dependency change

### Writing Tips

- Subject ≤ 72 characters, imperative voice, no trailing period.
- Describe motivation in the body if the diff is not self-explanatory.
- Reference issues when relevant (`Closes: #123`).

### Examples

```
feat(http_retry): add exponential backoff with jitter

Support transient failures more gracefully by adding jittered backoff.

Closes: #456
```

```
fix(constraints): handle missing constraint file gracefully

Validate file existence and emit a helpful message instead of crashing.
```

Avoid vague messages like `fix bug`, `update files`, or `WIP`.

---

## Before Submitting

### Quality Checklist

- [ ] `hatch run lint:fix`
- [ ] `hatch run test:test`
- [ ] `hatch run mypy:check`
- [ ] `hatch run lint:check`

### Code Review Checklist

- [ ] Every function is fully typed.
- [ ] Public APIs include docstrings.
- [ ] Tests cover the change (positive + edge cases).
- [ ] No trailing whitespace; files end with a newline.
- [ ] Conventional Commit format followed.
- [ ] Code aligns with existing patterns.

---

## Design Patterns Used in Fromager

### Context Managers

```python
@contextlib.contextmanager
def resource_context() -> typing.Generator[None, None, None]:
    """Manage resource lifecycle."""
    setup_resource()
    try:
        yield
    finally:
        cleanup_resource()
```

### Thread-Safe Decorators

```python
def with_thread_lock() -> typing.Callable:
    """Create thread-safe wrapper."""
    lock = threading.Lock()

    def decorator(func: typing.Callable) -> typing.Callable:
        @functools.wraps(func)
        def wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
            with lock:
                return func(*args, **kwargs)
        return wrapper
    return decorator
```

### Pydantic Validation

```python
def _validate_envkey(value: typing.Any) -> str:
    """Normalize environment variable keys."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    raise TypeError(f"unsupported type {type(value)}: {value!r}")

EnvKey = typing.Annotated[str, BeforeValidator(_validate_envkey)]
```

---

## Quick Reference

### Commands

| Task | Command |
|------|---------|
| Run tests | `hatch run test:test` |
| Check code quality | `hatch run lint:check` |
| Fix formatting | `hatch run lint:fix` |
| Type checking | `hatch run mypy:check` |

### Standards

| Standard | Requirement |
|----------|-------------|
| Type annotations | Required for every function |
| Docstrings | Required on public APIs |
| Tests | Required for new behavior |
| Trailing whitespace | Forbidden |
| File endings | Single newline |
| Commit format | Conventional Commits |

---

## Getting Help

- Open an issue for discussion or questions or design proposals.
- File an issue with a minimal reproduction for bugs.
- Ask for targeted feedback directly in your pull request.

## Resources

- [PEP 8 - Style Guide](https://www.python.org/dev/peps/pep-0008/)
- [PEP 484 - Type Hints](https://www.python.org/dev/peps/pep-0484/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [pytest Documentation](https://docs.pytest.org/)
- [Ruff Documentation](https://docs.astral.sh/ruff/)

---

**Thanks for contributing to Fromager!** If you spot gaps or have suggestions for this guide, open an issue or start a discussion—we love improving our contributor experience.
