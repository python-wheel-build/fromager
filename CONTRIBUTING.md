# Contributing to Fromager

Fromager thrives on practical, well-tested contributions. This guide summarizes how to set up a workspace, follow our standards, and submit polished changes. Skim it once, keep it handy, and refer back whenever you are unsure.

> **Note**: If you're using AI coding assistants, also see [AGENTS.md](AGENTS.md) for AI-optimized quick reference.

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

  ```bash
  pip install hatch
  # or
  pipx install hatch  # recommended
  ```

### Initial Setup

```bash
# 1. Fork the repository on GitHub
# 2. Clone your fork
git clone https://github.com/<your-username>/fromager.git
cd fromager

# 3. Add upstream remote
git remote add upstream https://github.com/python-wheel-build/fromager.git

# 4. Create development environment
hatch env create
```

### Contribution Workflow

```bash
# 1. Sync with upstream
git checkout main
git fetch upstream
git merge upstream/main

# 2. Create a feature branch
git checkout -b feat/<short-description>

# 3. Make changes and test as you go
hatch run test:test tests/test_<module>.py       # Test your specific changes

# 4. Before committing, run full quality checks
hatch run lint:fix && hatch run test:test && hatch run mypy:check && hatch run lint:check

# 5. Commit using Conventional Commits
git commit -m "feat(scope): short summary"

# 6. Push to your fork
git push origin feat/<short-description>

# 7. Create a pull request on GitHub
```

---

## Coding Standards

### Type Annotations

- Every function (including tests) must annotate all parameters and return values.
- Use modern `X | None` syntax instead of `Optional[X]` (requires Python 3.11+).
- Prefer precise collection types (`list[str]`, `dict[str, int]`, etc.).

```python
def process(data: str | None, count: int = 0) -> dict[str, int]:
    """Process the input and return aggregate counts."""
    return {}
```

### Code Quality and Formatting

- Ruff enforces both formatting and linting.
- Run `hatch run lint:fix` to automatically format code.
- See [Quick Reference](#quick-reference) for additional commands.

### Import Organization

- **PEP 8: imports should be at the top**: All import statements must be placed at the top of the file, after module docstrings and before other code.
- **No local imports**: Do not place import statements inside functions, methods, or conditional blocks.

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

# When processing a specific package, wrap calls to include package info in logs
# req: Requirement object for the package being processed
# version: Version string being built (optional)
with req_ctxvar_context(req, version):
    logger.info("Resolving build dependencies")  # Logs will include package name
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

```text
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

```text
feat(http_retry): add exponential backoff with jitter

Support transient failures more gracefully by adding jittered backoff.

Closes: #456
```

```text
fix(constraints): handle missing constraint file gracefully

Validate file existence and emit a helpful message instead of crashing.
```

### AI-Generated Code Attribution

When AI tools create or significantly modify code, add attribution:

```text
feat(resolver): add exponential backoff for HTTP retries

Improves resilience when PyPI is under load by adding jittered backoff.

Co-Authored-By: Claude <claude@anthropic.com>
Closes: #456
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
| ------ | --------- |
| Run tests | `hatch run test:test` |
| Check code quality | `hatch run lint:check` |
| Fix formatting | `hatch run lint:fix` |
| Type checking | `hatch run mypy:check` |

### Standards

| Standard | Requirement |
| ---------- | ------------- |
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
