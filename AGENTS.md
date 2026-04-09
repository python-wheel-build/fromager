# AI Agent Guide for Fromager

> **Note**: This file is also available as `CLAUDE.md` (symlink) for Claude Code CLI users.
>
> **You MUST read [CONTRIBUTING.md](CONTRIBUTING.md) before writing code.** It contains coding standards, type annotation rules, design patterns, and commit message format. This file provides agent-specific quick reference only.

## Essential Rules (MUST FOLLOW)

### Do

- Keep all written text concise and easy to understand — docstrings, comments, commit messages, PR descriptions, and documentation
- Add docstrings on all public functions and classes
- Use file-scoped commands for fast feedback (see below)
- Follow existing patterns — search codebase for similar code
- Chain exceptions: `raise ValueError(...) from err`
- Use `req_ctxvar_context()` for per-requirement logging
- Run `hatch run lint:fix` to format code

### Don't

- Don't run full test suite for small changes (use file-scoped)
- Don't create temporary helper scripts or workarounds
- Don't commit without running quality checks
- Don't make large speculative changes — ask first or propose a plan
- Don't update git config or force push to main
- Don't use bare `except:` — always specify exception types
- Don't invent new patterns — search the codebase for existing ones

## Commands (IMPORTANT: Use File-Scoped First)

### Setup (Run Once)

```bash
hatch run lint:install-hooks    # Pre-commit hooks for automatic formatting
```

### File-Scoped (PREFER THESE)

```bash
hatch run mypy:check <filepath>                          # Type check single file
hatch run lint:fix <filepath>                            # Format single file
hatch run test:test tests/test_<module>.py               # Test specific file
hatch run test:test tests/test_<module>.py::test_name    # Test specific function
hatch run test:test <filepath> --log-level DEBUG         # Debug test
```

### Project-Wide (ASK BEFORE RUNNING)

```bash
hatch run lint:fix       # Format all code
hatch run test:test      # Full test suite (slow!)
hatch run mypy:check     # Type check everything
hatch run lint:check     # Final lint check
hatch run lint:precommit # All linters and pre-commit hooks
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

- `src/fromager/` — Main package code
- `tests/` — Unit tests (mirror `src/` structure)
- `e2e/` — End-to-end integration tests
- `docs/` — Sphinx documentation

### Reference Files for Patterns

Look at these before writing code:

- Type annotations: `src/fromager/context.py`
- Pydantic models: `src/fromager/packagesettings.py`
- Logging with context: `src/fromager/resolver.py`
- Error handling: `src/fromager/commands.py`
- Testing patterns: `tests/test_context.py`

## Code Patterns

**Import rules:** All imports at the top of the file, no local imports. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

**Testing:** Use Arrange/Act/Assert pattern, name functions `test_<behavior>()`. See `tests/test_context.py` for examples.

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) — see [CONTRIBUTING.md](CONTRIBUTING.md) for format, types, and examples.

When AI agents create or significantly modify code, add attribution:

```text
feat(scope): short summary

Body explaining what and why.

Co-Authored-By: Claude <claude@anthropic.com>
Closes: #123
```

## Workflow for Complex Tasks

1. **Search codebase** for similar patterns first
2. **Create a checklist** for tracking progress
3. **Work through items** one at a time
4. **Run file-scoped tests** after each change
5. **Run full quality checks** only at the end: `hatch run lint:fix && hatch run test:test && hatch run mypy:check && hatch run lint:check`

---

**See [CONTRIBUTING.md](CONTRIBUTING.md) for comprehensive standards, detailed examples, and design patterns.**
