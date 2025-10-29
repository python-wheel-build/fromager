# Contributor Quickstart Guide

## Commit Message Guidelines

### Objectives

- Help the user craft commit messages that follow best practices
- Use [Conventional Commit](https://www.conventionalcommits.org/en/v1.0.0/) format unless otherwise specified
- Clarify unclear or incomplete input with targeted questions
- Ensure messages are concise, informative, and use imperative mood

### Style Guidelines

- Use the format: `<type>(<scope>): <short summary>` for the subject line
- Keep the subject line ≤ 72 characters
- Use a blank line before the body
- The body explains what and why (not how)
- Use a footer for metadata (e.g., `Closes: #123`, `BREAKING CHANGE:`)

### Commit Types

- **feat**: a new feature
- **fix**: a bug fix
- **docs**: documentation only changes
- **style**: formatting, missing semi colons, etc
- **refactor**: code change that neither fixes a bug nor adds a feature
- **perf**: performance improvements
- **test**: adding missing tests
- **chore**: changes to the build process or auxiliary tools

### Examples

#### Good commit messages

```text
feat(api): add user authentication endpoint

Add JWT-based authentication system for secure API access.
Includes token generation, validation, and refresh functionality.

Closes: #123
```

```text
fix(parser): handle empty input gracefully

Previously, empty input would cause a null pointer exception.
Now returns an appropriate error message.
```

```text
docs: update installation instructions

Add missing dependency requirements and clarify setup steps
for new contributors.
```

#### Poor commit messages to avoid

- `fix bug` (too vague)
- `updated files` (not descriptive)
- `WIP` (not informative)
- `fixed the thing that was broken` (not professional)

### Best Practices

- Write in imperative mood (e.g., "add feature" not "added feature")
- Don't end the subject line with a period
- Use the body to explain the motivation for the change
- Reference issues and pull requests where relevant
- Use `BREAKING CHANGE:` in footer for breaking changes

## Code Quality Guidelines

### Formatting Standards

- **No trailing whitespace**: Ensure no extra spaces at the end of lines
- **No whitespace on blank lines**: Empty lines should contain no spaces or tabs
- **Include a blank line as EOF**: Every file should end with a newline character
- Follow the project's existing code style and indentation patterns
- Use consistent line endings (LF for this project)

### Testing After Code Changes

After making code changes, run the following tests within a Python virtual environment to ensure code quality:

#### Run all unit tests

```bash
hatch run test:test
```

#### Run lint checks

```bash
hatch run lint:check
```

#### Run mypy type checking

```bash
hatch run mypy:check
```

### Before Committing

- Review your changes for trailing whitespace: `git diff | grep -E "^\+.*[[:space:]]$"`
- Run tests to ensure all changes work correctly
- Check for linting errors if the project uses linters
