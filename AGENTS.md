# AI Agent Guide for Fromager

> **Note**: This file is also available as `CLAUDE.md` (symlink) for Claude Code CLI users.
>
> **IMPORTANT**: Before making any code changes, you MUST read [CONTRIBUTING.md](CONTRIBUTING.md) for comprehensive coding standards and design patterns. This file provides essential quick reference only.

## When to Read CONTRIBUTING.md

**Always read CONTRIBUTING.md before:**

- Writing new functions (for type annotation standards)
- Adding imports (for import organization rules)
- Creating tests (for testing patterns)
- Making commits (for commit message format)
- Adding error handling or logging

## Essential Rules (MUST FOLLOW)

### Do

- **Type annotations REQUIRED** on ALL functions including tests. Use syntax compatible with Python 3.11+
- Use `X | None` not `Optional[X]`
- Add docstrings on all public functions and classes
- Use file-scoped commands for fast feedback (see below)
- Follow existing patterns - search codebase for similar code
- Chain exceptions: `raise ValueError(...) from err`
- Use `req_ctxvar_context()` for per-requirement logging
- Run `hatch run lint:fix` to format code (handles line length, whitespace, etc.)

### Don't

- Don't use `Optional[X]` syntax (use `X | None`)
- Don't omit type annotations or return types
- Don't run full test suite for small changes (use file-scoped)
- Don't create temporary helper scripts or workarounds
- Don't commit without running quality checks
- Don't make large speculative changes without asking
- Don't update git config or force push to main
- Don't use bare `except:` - always specify exception types

## Commands (IMPORTANT: Use File-Scoped First)

### File-Scoped Commands (PREFER THESE)

```bash
# Type check single file
hatch run mypy:check <filepath>

# Format single file
hatch run lint:fix <filepath>

# Test specific file
hatch run test:test tests/test_<module>.py

# Test specific function
hatch run test:test tests/test_<module>.py::test_function_name

# Debug test with verbose output
hatch run test:test <filepath> --log-level DEBUG
```

### Project-Wide Commands (ASK BEFORE RUNNING)

```bash
hatch run lint:fix      # Format all code
hatch run test:test     # Full test suite (slow!)
hatch run mypy:check    # Type check everything
hatch run lint:check    # Final lint check
```

## Safety and Permissions

### Allowed Without Asking

- Read files, search codebase
- Run file-scoped linting, type checking, tests
- Edit existing files following established patterns
- Create test files

### Ask First

- Installing/updating packages in pyproject.toml
- Git commit or push operations
- Deleting files or entire modules
- Running full test suite
- Creating new modules or major refactors
- Making breaking changes

## Project Structure

- `src/fromager/` - Main package code
- `tests/` - Unit tests (mirror `src/` structure)
- `e2e/` - End-to-end integration tests
- `docs/` - Sphinx documentation

### Reference Files for Patterns

**Before writing code, look at these examples:**

- Type annotations: `src/fromager/context.py`
- Pydantic models: `src/fromager/packagesettings.py`
- Logging with context: `src/fromager/resolver.py`
- Error handling: `src/fromager/commands.py`
- Testing patterns: `tests/test_context.py`

## Code Patterns

**Import Guidelines:**

- **PEP 8: imports should be at the top**: All import statements must be placed at the top of the file, after module docstrings and before other code
- **No local imports**: Do not place import statements inside functions, methods, or conditional blocks

### Testing Pattern

```python
def test_behavior(tmp_path: pathlib.Path) -> None:
    """Verify expected behavior."""
    # Arrange
    config = tmp_path / "config.txt"
    config.write_text("key=value\n")
    # Act
    result = load_config(config)
    # Assert
    assert result["key"] == "value"
```

## Commit Message Format (REQUIRED)

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) format:

```text
<type>(<scope>): <short summary>

<body explaining what + why>

<footer: Closes: #123>
```

### Types

- **feat**: new functionality
- **fix**: bug fix
- **docs**: documentation only
- **test**: tests only
- **refactor**: behavioral no-op refactor
- **perf**: performance improvement
- **chore**: tooling or dependency change

### Good Examples

```text
feat(resolver): add exponential backoff for HTTP retries

Improves resilience when PyPI is under load by adding jittered backoff.

Closes: #123
```

```text
fix(constraints): handle missing constraint file gracefully

Validate file existence and emit helpful message instead of crashing.
```

### AI Agent Attribution

When AI agents create or significantly modify code, add attribution using `Co-Authored-By`:

```text
feat(resolver): add exponential backoff for HTTP retries

Improves resilience when PyPI is under load by adding jittered backoff.

Co-Authored-By: Claude <claude@anthropic.com>
Closes: #123
```

### Bad Examples (NEVER DO THIS)

- `fix bug` (too vague)
- `updated files` (not descriptive)
- `WIP` (not informative)
- `fixed the thing that was broken` (not professional)

## Workflow for Complex Tasks

1. **Search codebase** for similar patterns first
2. **Create a checklist** in a markdown file for tracking
3. **Work through items systematically** one at a time
4. **Run file-scoped tests** after each change
5. **Check off completed items** before moving to next
6. **Run full quality checks** only at the end

## When Uncertain

- Ask clarifying questions rather than making assumptions
- Search the codebase for similar patterns before inventing new ones
- Propose a specific plan before making large changes
- Reference [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidance
- **DO NOT** make large speculative changes without confirmation

## Quality Checklist Before Finishing

- [ ] Read CONTRIBUTING.md for relevant standards
- [ ] Type annotations on all functions
- [ ] Docstrings on public APIs
- [ ] Tests cover the change
- [ ] File-scoped tests pass
- [ ] No trailing whitespace
- [ ] File ends with single newline
- [ ] Conventional Commit format used
- [ ] Full quality checks pass: `hatch run lint:fix && hatch run test:test && hatch run mypy:check && hatch run lint:check`

---

**See [CONTRIBUTING.md](CONTRIBUTING.md) for comprehensive standards, detailed examples, and design patterns used in Fromager.**
