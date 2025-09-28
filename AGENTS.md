# Contributor Quickstart Guide

## Testing

Use `hatch run test:test` to run unit tests.

Use `hatch run lint:check` to run the linter.

Use `hatch run mypy:check` to run mypy to check for type annotation issues.

The end-to-end tests are in shell scripts in the `e2e` subdirectory.

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
